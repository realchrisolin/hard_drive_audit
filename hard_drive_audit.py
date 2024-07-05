import curses
import pyperclip
import dataclasses
from typing import List, Optional
import win32com.client
import win32api
import win32con
import win32file
import winioctlcon
import struct
import uuid
from functools import lru_cache


@dataclasses.dataclass
class Volume:
    drive_letter: str
    file_system: str
    capacity: int
    free_space: int
    label: str
    bitlocker_status: str


@dataclasses.dataclass
class Partition:
    index: int
    size: int
    type: str
    drive_letter: str
    file_system: str
    bitlocker_status: str
    type_guid: str
    unique_guid: str
    known_type: str
    first_bytes: str


@dataclasses.dataclass
class Disk:
    index: int
    device_id: str
    model: str
    serial_number: str
    disk_type: str
    partitions: List[Partition]


@dataclasses.dataclass
class System:
    disks: List[Disk]


def get_wmi_service(namespace="root\\cimv2"):
    return win32com.client.Dispatch("WbemScripting.SWbemLocator").ConnectServer(".", namespace)


@lru_cache(maxsize=None)
def get_known_partition_type(guid):
    gpt_guids = {
        'e3c9e316-0b5c-4db8-817d-f92df00215ae': 'Microsoft Reserved Partition (MSR)',
        'ebd0a0a2-b9e5-4433-87c0-68b6b72699c7': 'Basic Data Partition',
        'de94bba4-06d1-4d40-a16a-bfd50179d6ac': 'Windows Recovery Environment',
        'c12a7328-f81f-11d2-ba4b-00a0c93ec93b': 'EFI System Partition',
        '5808c8aa-7e8f-42e0-85d2-e1e90434cfb3': 'Linux Filesystem Data',
        '0fc63daf-8483-4772-8e79-3d69d8477de4': 'Linux Filesystem'
    }
    mbr_guids = {
        '0x00': 'Empty',
        '0x01': 'FAT12',
        '0x04': 'FAT16 <32MB',
        '0x05': 'Extended',
        '0x06': 'FAT16',
        '0x07': 'NTFS/exFAT',
        '0x0B': 'FAT32',
        '0x0C': 'FAT32 (LBA)',
        '0x0E': 'FAT16 (LBA)',
        '0x0F': 'Extended (LBA)',
        '0x82': 'Linux swap',
        '0x83': 'Linux',
        '0x8E': 'Linux LVM',
        '0xA5': 'FreeBSD',
        '0xA6': 'OpenBSD',
        '0xAF': 'Mac OS X HFS+'
    }
    if guid.startswith('0x'):
        return mbr_guids.get(guid, 'Unknown MBR identifier')
    else:
        return gpt_guids.get(guid.lower(), 'Unknown GPT identifier')


def get_disk_type(disk_number):
    drive_handle = win32file.CreateFile(
        f"\\\\.\\PhysicalDrive{disk_number}",
        win32file.GENERIC_READ,
        win32file.FILE_SHARE_READ | win32file.FILE_SHARE_WRITE,
        None,
        win32file.OPEN_EXISTING,
        0,
        None
    )

    try:
        output_buffer = win32file.DeviceIoControl(
            drive_handle,
            winioctlcon.IOCTL_DISK_GET_DRIVE_LAYOUT_EX,
            None,
            32768
        )

        partition_style, _ = struct.unpack_from("<II", output_buffer)

        if partition_style == 1:
            return "GPT"
        elif partition_style == 0:
            return "MBR"
        else:
            return "Unknown"

    except win32file.error as e:
        return f"Error: {str(e)}"
    finally:
        win32file.CloseHandle(drive_handle)


def parse_partition_data(disk_number, partition_number, disk_type):
    drive_handle = win32file.CreateFile(
        f"\\\\.\\PhysicalDrive{disk_number}",
        win32file.GENERIC_READ,
        win32file.FILE_SHARE_READ | win32file.FILE_SHARE_WRITE,
        None,
        win32file.OPEN_EXISTING,
        0,
        None
    )

    try:
        if disk_type == "GPT":
            output_buffer = win32file.DeviceIoControl(
                drive_handle,
                winioctlcon.IOCTL_DISK_GET_DRIVE_LAYOUT_EX,
                None,
                32768
            )

            _, partition_count = struct.unpack_from("<II", output_buffer)

            offset = 48  # Start of partition entries
            for i in range(partition_count):
                if offset + 128 > len(output_buffer):
                    return "Not found", "Not found"

                alignment_offset = [0, 16, 32, 48][i]
                part_info = output_buffer[offset + alignment_offset:offset + alignment_offset + 128]

                part_number, = struct.unpack_from("<I", part_info, 24)
                if part_number == partition_number + 1:  # Adjust for 0-based index
                    type_guid = uuid.UUID(bytes_le=part_info[32:48])
                    unique_guid = uuid.UUID(bytes_le=part_info[48:64])
                    return str(type_guid).upper(), str(unique_guid).upper()

                offset += 128  # Move to the next partition entry

            return "Not found", "Not found"

        elif disk_type == "MBR":
            error, mbr = win32file.ReadFile(drive_handle, 512)
            if error:
                return f"Error reading MBR: {win32api.FormatMessage(error)}", "N/A"

            partition_table_offset = 446
            partition_entry_size = 16
            partition_offset = partition_table_offset + (partition_number * partition_entry_size)

            if partition_offset + partition_entry_size > len(mbr):
                return "Invalid partition number", "N/A"

            partition_entry = mbr[partition_offset:partition_offset + partition_entry_size]
            partition_type = partition_entry[4]

            return f"0x{partition_type:02X}", "N/A"

        else:
            return "Unknown disk type", "N/A"

    except win32file.error as e:
        return f"Error: {str(e)}", "Error"
    finally:
        win32file.CloseHandle(drive_handle)


def get_bitlocker_status(drive_letter):
    try:
        wmi_service = get_wmi_service("root\\cimv2\\Security\\MicrosoftVolumeEncryption")
        volumes = wmi_service.ExecQuery(f"SELECT * FROM Win32_EncryptableVolume WHERE DriveLetter = '{drive_letter}'")

        for volume in volumes:
            protection_status = volume.ProtectionStatus
            conversion_status = volume.ConversionStatus

            if protection_status == 0:
                return "Not Encrypted"
            elif protection_status == 1 or (protection_status == 2 and conversion_status == -1):
                return "Encrypted"
            elif protection_status == 2:
                return "Encryption in Progress"
    except Exception:
        pass

    try:
        root_path = f"{drive_letter}\\"
        if (win32api.GetFileAttributes(root_path + "$BitLocker.mbr") != win32con.INVALID_FILE_ATTRIBUTES or
                win32api.GetFileAttributes(
                    root_path + "System Volume Information\\FVE2.{5770e5e3-bcb1-11d0-a96f-00c04fd6565b}") != win32con.INVALID_FILE_ATTRIBUTES):
            return "Likely Encrypted"
    except:
        pass

    try:
        drive_type = win32api.GetDriveType(drive_letter)
        if drive_type == win32con.DRIVE_REMOVABLE:
            return "Removable Drive (BitLocker To Go?)"
        elif drive_type != win32con.DRIVE_FIXED:
            return f"Not a Fixed Drive (Type: {drive_type})"
    except:
        pass

    return "Unable to determine"


def get_partition_hex_data(disk_number, partition):
    drive_handle = win32file.CreateFile(
        f"\\\\.\\PhysicalDrive{disk_number}",
        win32file.GENERIC_READ,
        win32file.FILE_SHARE_READ | win32file.FILE_SHARE_WRITE,
        None,
        win32file.OPEN_EXISTING,
        0,
        None
    )

    try:
        start_sector = int(partition.StartingOffset) // 512
        win32file.SetFilePointer(drive_handle, start_sector * 512, win32file.FILE_BEGIN)
        error, data = win32file.ReadFile(drive_handle, 512)
        if error == 0:
            return data.hex()
        else:
            return f"Error reading data: {win32api.FormatMessage(error)}"
    except Exception as e:
        return f"Error: {str(e)}"
    finally:
        win32file.CloseHandle(drive_handle)


def get_volume_info(partition_device_id):
    wmi_service = get_wmi_service()

    # First, get the associated logical disk
    query = f"ASSOCIATORS OF {{Win32_DiskPartition.DeviceID='{partition_device_id}'}} WHERE AssocClass = Win32_LogicalDiskToPartition"
    logical_disks = wmi_service.ExecQuery(query)

    for logical_disk in logical_disks:
        # Now use the DeviceID from the logical disk to query Win32_Volume
        volume_query = f"SELECT * FROM Win32_Volume WHERE DriveLetter = '{logical_disk.DeviceID}'"
        volumes = wmi_service.ExecQuery(volume_query)

        for volume in volumes:
            return Volume(
                drive_letter=volume.DriveLetter or 'N/A',
                file_system=volume.FileSystem or 'N/A',
                capacity=volume.Capacity,
                free_space=volume.FreeSpace,
                label=volume.Label or 'N/A',
                bitlocker_status=get_bitlocker_status(volume.DriveLetter)
            )

    # If no volume is found, return a default Volume object
    return Volume(
        drive_letter='N/A',
        file_system='N/A',
        capacity=0,
        free_space=0,
        label='N/A',
        bitlocker_status='N/A'
    )


def get_partition(disk_index, partition, disk_type):
    type_guid, unique_guid = parse_partition_data(disk_index, partition.Index, disk_type)
    volume = get_volume_info(partition.DeviceID)

    return Partition(
        index=partition.Index,
        size=int(partition.Size),
        type=partition.Type,
        drive_letter=volume.drive_letter if volume else 'N/A',
        file_system=volume.file_system if volume else 'N/A',
        bitlocker_status=volume.bitlocker_status if volume else 'N/A',
        type_guid=type_guid,
        unique_guid=unique_guid,
        known_type=get_known_partition_type(type_guid),
        first_bytes=get_partition_hex_data(disk_index, partition)
    )


def get_partitions(disk_index, disk_type):
    wmi_service = get_wmi_service()
    disk_partitions = wmi_service.ExecQuery(f"SELECT * FROM Win32_DiskPartition WHERE DiskIndex = {disk_index}")

    return [get_partition(disk_index, partition, disk_type) for partition in disk_partitions]


def get_disks():
    wmi_service = get_wmi_service()
    disk_drives = wmi_service.ExecQuery("SELECT * FROM Win32_DiskDrive")

    disks = []
    for disk in disk_drives:
        disk_type = get_disk_type(disk.Index)
        disks.append(Disk(
            index=disk.Index,
            device_id=disk.DeviceID,
            model=disk.Model.strip() if disk.Model else "N/A",
            serial_number=disk.SerialNumber.strip() if disk.SerialNumber else "N/A",
            disk_type=disk_type,
            partitions=get_partitions(disk.Index, disk_type)
        ))

    return disks


def get_system_info():
    return System(disks=get_disks())


def create_windows(stdscr, extra_rows=0):
    physical_height, width = stdscr.getmaxyx()
    total_height = physical_height + extra_rows
    gap_width = 1

    left_width = (width - gap_width) // 2
    right_width = width - left_width - gap_width

    left_pad = curses.newpad(total_height, left_width)
    right_pad = curses.newpad(total_height, right_width)

    for y in range(total_height):
        stdscr.addch(min(y, physical_height - 1), left_width, curses.ACS_VLINE)

    stdscr.refresh()

    return left_pad, right_pad, physical_height

def display_drive_selection(left_pad, disks, selected_index, start_index, is_active):
    left_pad.clear()
    height, width = left_pad.getmaxyx()
    left_pad.addstr(0, 0, "Physical Drives:")
    for idx, disk in enumerate(disks[start_index:], start=start_index):
        if idx - start_index + 2 >= height:
            break
        drive_info = f"Disk {disk.index}: {disk.model[:width - 20]}"
        if idx == selected_index and is_active:
            left_pad.attron(curses.A_REVERSE)
            left_pad.addnstr(idx - start_index + 2, 2, drive_info, width - 3)
            left_pad.attroff(curses.A_REVERSE)
        else:
            left_pad.addnstr(idx - start_index + 2, 2, drive_info, width - 3)

def display_partition_info(right_pad, disk, partitions, current_partition, scroll_position, is_active):
    right_pad.clear()
    height, width = right_pad.getmaxyx()
    right_pad.addstr(0, 0, f"Disk and Partition Information (Partitions: {len(partitions)}, Current: {current_partition + 1}):")

    if not partitions:
        right_pad.addstr(2, 2, "No partitions found")
        return

    disk_info = [
        f"Disk Model: {disk.model}",
        f"Disk Serial: {disk.serial_number}",
        f"Disk Type: {disk.disk_type}"
    ]

    part = partitions[current_partition]
    partition_info = [
        f"Partition Index: {part.index}",
        f"Size: {part.size / (1024**3):.2f} GB",
        f"Type: {part.type}",
        f"Drive Letter: {part.drive_letter}",
        f"File System: {part.file_system}",
        f"BitLocker Status: {part.bitlocker_status}",
        f"Type GUID: {part.type_guid}",
        f"Unique GUID: {part.unique_guid}",
        f"Known Type: {part.known_type}",
        "First 512 bytes:",
        part.first_bytes[:64],
        part.first_bytes[64:128],
        part.first_bytes[128:192],
        part.first_bytes[192:256]
    ]

    lines = disk_info + [""] + partition_info

    for idx, line in enumerate(lines[scroll_position:], start=2):
        if idx >= height:
            break
        if idx == 2 and is_active:
            right_pad.attron(curses.A_REVERSE)
            right_pad.addnstr(idx, 2, line, width - 3)
            right_pad.attroff(curses.A_REVERSE)
        else:
            right_pad.addnstr(idx, 2, line, width - 3)


def copy_partition_info_to_clipboard(disk, partition):
    info = [
        f"Disk Information:",
        f"Model: {disk.model}",
        f"Serial Number: {disk.serial_number}",
        f"Disk Type: {disk.disk_type}",
        f"",
        f"Partition Information:",
        f"Index: {partition.index}",
        f"Size: {partition.size / (1024**3):.2f} GB",
        f"Type: {partition.type}",
        f"Drive Letter: {partition.drive_letter}",
        f"File System: {partition.file_system}",
        f"BitLocker Status: {partition.bitlocker_status}",
        f"Type GUID: {partition.type_guid}",
        f"Unique GUID: {partition.unique_guid}",
        f"Known Type: {partition.known_type}",
        f"First 512 bytes:",
        partition.first_bytes[:64],
        partition.first_bytes[64:128],
        partition.first_bytes[128:192],
        partition.first_bytes[192:256]
    ]

    clipboard_content = "\n".join(info)
    pyperclip.copy(clipboard_content)
    return "Disk and partition information copied to clipboard!"


def main(stdscr):
    curses.curs_set(0)  # Hide the cursor
    stdscr.clear()
    curses.use_default_colors()

    extra_rows = 100  # Adjust this value to increase the number of rows
    left_pad, right_pad, physical_height = create_windows(stdscr, extra_rows)

    system = get_system_info()
    current_drive_selection = 0
    current_partition = 0
    left_scroll = 0
    right_scroll = 0
    active_pane = 'left'
    status_message = ""

    while True:
        selected_disk = system.disks[current_drive_selection]
        partitions = selected_disk.partitions

        # Ensure current_partition is within valid range
        if current_partition >= len(partitions):
            current_partition = max(0, len(partitions) - 1)

        display_drive_selection(left_pad, system.disks, current_drive_selection, left_scroll, active_pane == 'left')
        display_partition_info(right_pad, selected_disk, partitions, current_partition, right_scroll, active_pane == 'right')

        # Display status message
        stdscr.addstr(physical_height - 1, 0, status_message[:physical_height - 1].ljust(physical_height - 1))
        status_message = ""  # Clear status message after displaying

        # Get the dimensions of the screen and pads
        screen_height, screen_width = stdscr.getmaxyx()
        left_height, left_width = left_pad.getmaxyx()
        right_height, right_width = right_pad.getmaxyx()

        # Calculate the maximum scroll positions
        max_left_scroll = max(0, left_height - screen_height)
        max_right_scroll = max(0, right_height - screen_height)

        # Refresh the visible portion of the pads
        left_pad.refresh(left_scroll, 0, 0, 0, screen_height - 2, left_width - 1)
        right_pad.refresh(right_scroll, 0, 0, left_width + 1, screen_height - 2, screen_width - 1)

        key = stdscr.getch()
        if key == ord('q'):
            break
        elif key == 9:  # Tab key
            active_pane = 'right' if active_pane == 'left' else 'left'
        elif key == ord('c'):  # 'c' key to copy partition info
            if partitions:
                status_message = copy_partition_info_to_clipboard(selected_disk, partitions[current_partition])
        elif key == curses.KEY_UP:
            if active_pane == 'left':
                if current_drive_selection > 0:
                    current_drive_selection -= 1
                    current_partition = 0  # Reset partition selection when changing drives
                    right_scroll = 0
                left_scroll = max(0, left_scroll - 1)
            else:
                right_scroll = max(0, right_scroll - 1)
        elif key == curses.KEY_DOWN:
            if active_pane == 'left':
                if current_drive_selection < len(system.disks) - 1:
                    current_drive_selection += 1
                    current_partition = 0  # Reset partition selection when changing drives
                    right_scroll = 0
                left_scroll = min(left_scroll + 1, max_left_scroll)
            else:
                right_scroll = min(right_scroll + 1, max_right_scroll)
        elif active_pane == 'right':
            if key == curses.KEY_LEFT and current_partition > 0:
                current_partition -= 1
                right_scroll = 0
            elif key == curses.KEY_RIGHT and current_partition < len(partitions) - 1:
                current_partition += 1
                right_scroll = 0

        stdscr.refresh()

if __name__ == "__main__":
    curses.wrapper(main)