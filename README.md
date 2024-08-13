# README

Python utility that leverages Windows APIs / WMI to look up and display hard drive metadata

Must be run with admin privileges

# Software Bill of Materials (SBOM) for Disk Information Script

## Core Python Libraries
1. curses
2. dataclasses
3. typing
4. struct
5. uuid
6. functools

## External Libraries
1. win32com.client (from pywin32)
2. win32api (from pywin32)
3. win32con (from pywin32)
4. win32file (from pywin32)
5. winioctlcon (from pywin32)
6. pyperclip

## Custom Components
1. Volume (dataclass)
2. Partition (dataclass)
3. Disk (dataclass)
4. System (dataclass)

## Main Functions
1. get_wmi_service()
2. get_known_partition_type()
3. get_disk_type()
4. parse_partition_data()
5. get_bitlocker_status()
6. get_partition_hex_data()
7. get_volume_info()
8. get_partition()
9. get_partitions()
10. get_disks()
11. get_system_info()
12. create_windows()
13. display_drive_selection()
14. display_partition_info()
15. copy_partition_info_to_clipboard()
16. main()

## Version Information
- Python Version: 3.6+ (due to use of dataclasses)
- pywin32 Version: Compatible with the latest version as of August 2024
- pyperclip Version: Compatible with the latest version as of August 2024

## System Requirements
- Operating System: Windows (due to use of Win32 API)
- Architecture: Compatible with both 32-bit and 64-bit systems

## Notes
- This script is designed to run on Windows systems only, as it relies heavily on Windows-specific APIs and WMI queries.
- Administrative privileges may be required to access certain disk and partition information.
- The script uses a text-based user interface (TUI) implemented with the curses library.
- Clipboard functionality is provided through the pyperclip library.

## Security Considerations
- The script accesses low-level system information, which may require elevated privileges.
- Care should be taken when distributing or running this script, as it has the capability to read sensitive system information.

## Licensing
- The core Python libraries and win32 extensions are subject to their respective licenses.
- pyperclip is typically distributed under the BSD License.
- The custom code in this script should be licensed according to the project's requirements.
