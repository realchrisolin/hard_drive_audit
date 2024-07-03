import curses
import win32com.client
import win32api
import win32con
import win32file
import winioctlcon
import struct
import uuid

def get_wmi_service():
    return win32com.client.Dispatch("WbemScripting.SWbemLocator").ConnectServer(".", "root\\cimv2")

def get_physical_drives():
    wmi_service = get_wmi_service()
    disk_drives = wmi_service.ExecQuery("SELECT * FROM Win32_DiskDrive")
    return [{
        'DeviceID': disk.DeviceID,
        'Model': disk.Model,
        'SerialNumber': disk.SerialNumber,
        'Index': disk.Index
    } for disk in disk_drives]

def get_volume_info(partition_device_id):
    wmi_service = win32com.client.Dispatch("WbemScripting.SWbemLocator").ConnectServer(".", "root\\cimv2")
    volumes = wmi_service.ExecQuery(f"SELECT * FROM Win32_Volume WHERE DeviceID='{partition_device_id}'")

    for volume in volumes:
        return {
            'FileSystem': volume.FileSystem or 'N/A',
            'Capacity': volume.Capacity,
            'FreeSpace': volume.FreeSpace,
            'Label': volume.Label or 'N/A',
            'DriveLetter': volume.DriveLetter or 'N/A'
        }
    return None

def get_partition_type_gpt(disk_number, partition_number):
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
            32768  # Larger buffer size to accommodate full drive layout
        )

        partition_style, partition_count = struct.unpack_from("<II", output_buffer)

        if partition_style != 1:  # Not GPT
            return "Not a GPT disk", "Not a GPT disk"

        offset = 48  # Start of partition entries
        for i in range(partition_count):
            if offset + 128 > len(output_buffer):
                return f"Partition {partition_number} not found (buffer too short)", "Not found"

            alignment_offset = [0, 16, 32, 48][i]
            part_info = output_buffer[offset + alignment_offset:offset + alignment_offset + 128]

            part_number, = struct.unpack_from("<I", part_info, 24)
            if part_number == partition_number + 1:  # Adjust for 0-based index
                type_guid = uuid.UUID(bytes_le=part_info[32:48])
                unique_guid = uuid.UUID(bytes_le=part_info[48:64])
                return str(type_guid).upper(), str(unique_guid).upper()

            offset += 128  # Move to the next partition entry

        return f"Partition {partition_number} not found", "Not found"

    except win32file.error as e:
        return f"Error: {str(e)}", "Error"
    finally:
        win32file.CloseHandle(drive_handle)

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

def get_partition_type_mbr(disk_number, partition_number):
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
        error, mbr = win32file.ReadFile(drive_handle, 512)
        if error:
            return f"Error reading MBR: {win32api.FormatMessage(error)}"

        partition_table_offset = 446
        partition_entry_size = 16
        partition_offset = partition_table_offset + (partition_number * partition_entry_size)

        if partition_offset + partition_entry_size > len(mbr):
            return "Invalid partition number"

        partition_entry = mbr[partition_offset:partition_offset + partition_entry_size]
        partition_type = partition_entry[4]

        return f"0x{partition_type:02X}"
    finally:
        win32file.CloseHandle(drive_handle)

def get_partition_hex_data(disk_number, partitions):
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
        partition_data = {}
        for i, partition in enumerate(partitions):
            try:
                start_sector = int(partition.StartingOffset) // 512
                win32file.SetFilePointer(drive_handle, start_sector * 512, win32file.FILE_BEGIN)
                error, data = win32file.ReadFile(drive_handle, 512)
                if error == 0:
                    hex_data = data.hex()
                    partition_data[f"Partition {i + 1}"] = hex_data
                else:
                    partition_data[f"Partition {i + 1}"] = f"Error reading data: {win32api.FormatMessage(error)}"
            except Exception as e:
                partition_data[f"Partition {i + 1}"] = f"Error: {str(e)}"

        return partition_data

    finally:
        win32file.CloseHandle(drive_handle)

def get_partition_info(disk_index):
    wmi_service = get_wmi_service()
    partitions = []

    disk_query = f"SELECT * FROM Win32_DiskDrive WHERE Index = {disk_index}"
    disk_info = wmi_service.ExecQuery(disk_query)[0]
    disk_model = disk_info.Model.strip() if disk_info.Model else "N/A"
    disk_serial = disk_info.SerialNumber.strip() if disk_info.SerialNumber else "N/A"

    disk_partitions = wmi_service.ExecQuery(f"SELECT * FROM Win32_DiskPartition WHERE DiskIndex = {disk_index}")

    partition_hex_data = get_partition_hex_data(disk_index, disk_partitions)

    for idx, partition in enumerate(disk_partitions):
        partition_info = {
            'PartitionID': f"Disk #{disk_index}, Partition #{partition.Index}",
            'DiskModel': disk_model,
            'DiskSerial': disk_serial,
            'Size': int(partition.Size),
            'Type': partition.Type,
            'DriveLetter': 'N/A',
            'FileSystem': 'N/A',
            'BitLocker': 'N/A'
        }

        query = f"ASSOCIATORS OF {{Win32_DiskPartition.DeviceID='{partition.DeviceID}'}} WHERE AssocClass = Win32_LogicalDiskToPartition"
        logical_disks = wmi_service.ExecQuery(query)

        for logical_disk in logical_disks:
            partition_info['DriveLetter'] = logical_disk.DeviceID
            partition_info['FileSystem'] = logical_disk.FileSystem
            partition_info['BitLocker'] = get_bitlocker_status(logical_disk.DeviceID)

        partition_type_gpt, partition_unique_gpt = get_partition_type_gpt(disk_index, partition.Index)
        partition_info['PartitionTypeGUID'] = partition_type_gpt
        partition_info['PartitionUniqueGUID'] = partition_unique_gpt
        if partition_type_gpt == "Not a GPT disk":
            partition_type_mbr = get_partition_type_mbr(disk_index, partition.Index)
            partition_info['PartitionTypeGUID'] = partition_type_mbr
            partition_info['PartitionUniqueGUID'] = "N/A for MBR"
            partition_info['KnownPartitionType'] = get_known_partition_type(partition_type_mbr)
        else:
            partition_info['KnownPartitionType'] = get_known_partition_type(partition_type_gpt)

        partition_info['FirstBytes'] = partition_hex_data.get(f"Partition {idx + 1}", "Unable to read partition data")

        partitions.append(partition_info)

    return partitions


import pyperclip


def copy_partition_info_to_clipboard(partition):
    info = [
        f"Partition Information:",
        f"ID: {partition['PartitionID']}",
        f"Disk Model: {partition['DiskModel']}",
        f"Disk Serial: {partition['DiskSerial']}",
        f"Type: {partition['Type']}",
        f"Drive Letter: {partition['DriveLetter']}",
        f"Size: {partition['Size'] / (1024 ** 2):.2f} MB",
        f"File System: {partition['FileSystem']}",
        f"BitLocker: {partition['BitLocker']}",
        f"Type GUID: {partition['PartitionTypeGUID']}",
        f"Unique GUID: {partition['PartitionUniqueGUID']}",
        f"Known Type: {partition['KnownPartitionType']}"
    ]
    if 'Label' in partition:
        info.append(f"Label: {partition['Label']}")
    if 'FirstBytes' in partition:
        info.append("First 512 bytes:")
        hex_data = partition['FirstBytes']
        for i in range(0, len(hex_data), 32):
            info.append(hex_data[i:i + 32])

    clipboard_content = "\n".join(info)
    pyperclip.copy(clipboard_content)
    return "Partition information copied to clipboard!"


def get_bitlocker_status(drive_letter):
    try:
        wmi_service = win32com.client.Dispatch("WbemScripting.SWbemLocator").ConnectServer(".",
                                                                                           "root\\cimv2\\Security\\MicrosoftVolumeEncryption")
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

def display_drive_selection(left_pad, drives, selected_index, start_index, is_active):
    left_pad.clear()
    height, width = left_pad.getmaxyx()
    left_pad.addstr(0, 0, "Physical Drives:")
    for idx, drive in enumerate(drives[start_index:], start=start_index):
        if idx - start_index + 2 >= height:
            break
        drive_info = f"PHYSICALDRIVE{drive['Index']} - {drive['Model'][:width - 20]}"
        if idx == selected_index and is_active:
            left_pad.attron(curses.A_REVERSE)
            left_pad.addnstr(idx - start_index + 2, 2, drive_info, width - 3)
            left_pad.attroff(curses.A_REVERSE)
        else:
            left_pad.addnstr(idx - start_index + 2, 2, drive_info, width - 3)


def display_partition_info(right_pad, partitions, current_partition, scroll_position, is_active):
    right_pad.clear()
    height, width = right_pad.getmaxyx()
    right_pad.addstr(0, 0, f"Partition Information (Total: {len(partitions)}, Current: {current_partition + 1}):")

    if not partitions:
        right_pad.addstr(2, 2, "No partitions found")
        return

    part = partitions[current_partition]
    lines = [
        f"ID: {part['PartitionID']}",
        f"Disk Model: {part['DiskModel']}",
        f"Disk Serial: {part['DiskSerial']}",
        f"Type: {part['Type']}",
        f"Drive Letter: {part['DriveLetter']}",
        f"Size: {part['Size'] / (1024 ** 2):.2f} MB",
        f"FS: {part['FileSystem']}",
        f"BitLocker: {part['BitLocker']}",
        f"Type GUID: {part['PartitionTypeGUID']}",
        f"Unique GUID: {part['PartitionUniqueGUID']}",
        f"Known Type: {part['KnownPartitionType']}"
    ]
    if 'Label' in part:
        lines.append(f"Label: {part['Label']}")
    if 'FirstBytes' in part:
        lines.append("First 512 bytes:")
        hex_data = part['FirstBytes']
        for i in range(0, len(hex_data), 32):
            lines.append(hex_data[i:i + 32])

    for idx, line in enumerate(lines[scroll_position:], start=2):
        if idx >= height:
            break
        if idx == 2 and is_active:  # Highlight the first line of partition info when active
            right_pad.attron(curses.A_REVERSE)
            right_pad.addnstr(idx, 2, line, width - 3)
            right_pad.attroff(curses.A_REVERSE)
        else:
            right_pad.addnstr(idx, 2, line, width - 3)


def main(stdscr):
    curses.curs_set(0)  # Hide the cursor
    stdscr.clear()
    curses.use_default_colors()

    extra_rows = 100  # Adjust this value to increase the number of rows
    left_pad, right_pad, physical_height = create_windows(stdscr, extra_rows)

    physical_drives = get_physical_drives()
    current_drive_selection = 0
    current_partition = 0
    left_scroll = 0
    right_scroll = 0
    active_pane = 'left'
    status_message = ""

    while True:
        selected_drive = physical_drives[current_drive_selection]
        partitions = get_partition_info(selected_drive['Index'])

        # Ensure current_partition is within valid range
        if current_partition >= len(partitions):
            current_partition = max(0, len(partitions) - 1)

        display_drive_selection(left_pad, physical_drives, current_drive_selection, left_scroll, active_pane == 'left')
        display_partition_info(right_pad, partitions, current_partition, right_scroll, active_pane == 'right')

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
        left_pad.refresh(left_scroll, 0, 0, 0, screen_height - 1, left_width - 1)
        right_pad.refresh(right_scroll, 0, 0, left_width + 1, screen_height - 1, screen_width - 1)


        key = stdscr.getch()
        if key == ord('q'):
            break
        elif key == 9:  # Tab key
            active_pane = 'right' if active_pane == 'left' else 'left'
        elif key == ord('c'):  # 'c' key to copy partition info
            if partitions:
                status_message = copy_partition_info_to_clipboard(partitions[current_partition])
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
                if current_drive_selection < len(physical_drives) - 1:
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

if __name__ == "__main__":
    curses.wrapper(main)