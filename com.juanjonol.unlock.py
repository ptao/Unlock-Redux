#!/usr/local/bin/python3
"""
macOS daemon to decrypt CoreStorage (HFS+) and APFS Volumes automatically at launch.
Inspired by Unlock (https://github.com/jridgewell/Unlock).
"""

import re
import sys
import pathlib
import json
import os
import stat
import subprocess
import argparse
import getpass


passwords_path = "/Library/PrivilegedHelperTools/Generated_Files/com.juanjonol.unlock.json"
DISK_TYPE_APFS = 'APFS'
DISK_TYPE_CORESTORAGE = 'CoreStorage'


def main():
	if not sys.platform == 'darwin':
		raise NotImplementedError("This program only works in OS X")
	if os.getuid() != 0:
		raise PermissionError("This program must be executed as root (to save passwords in a secure way).")

	args = parse_args()

	if args.subcommand == "add":
		add_disk(disk=args.disk, uuid=args.uuid, disk_type=args.type, password=args.password)

	elif args.subcommand == "delete":
		delete_disk(disk=args.disk, uuid=args.uuid, disk_type=args.type, password=args.password)

	elif args.subcommand == "replace":
		replace_value(old_value=args.old, new_value=args.new)

	elif args.subcommand == "uuid":
		get_uuid(disk=args.disk)

	else:
		decrypt_disks()


# Parse the arguments given by the user.
def parse_args():

	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument('--version', action='version', version='2.2.1')
	subparsers = parser.add_subparsers(dest="subcommand")  # Store the used subcommand in the "subcommand" attribute

	execute_description = "Decrypt the disks whose UUID and password has been saved."
	subparsers.add_parser("execute", help=execute_description, description=execute_description)

	add_description = "Saves the UUID and password of a disk."
	add_command = subparsers.add_parser("add", help=add_description, description=add_description)
	path_or_uuid_group = add_command.add_mutually_exclusive_group()
	path_or_uuid_group.add_argument("-d", "--disk", help='Path to the disk, in the form "/dev/<disk>" or "/Volumes/<name>".')
	path_or_uuid_group.add_argument("-u", "--uuid", help="UUID of the disk.")
	add_command.add_argument("-t", "--type", help='Type of the disk ("CoreStorage" or "APFS"). Needed when using --uuid.')
	add_command.add_argument("-p", "--password", help="Password of the disk.")

	delete_description = "Deletes the UUID and password of a disk."
	delete_command = subparsers.add_parser("delete", help=delete_description, description=delete_description)
	path_or_uuid_group = delete_command.add_mutually_exclusive_group()
	path_or_uuid_group.add_argument("-d", "--disk", help='Path to the disk, in the form "/dev/<disk>" or "/Volumes/<name>".')
	path_or_uuid_group.add_argument("-u", "--uuid", help="UUID of the disk.")
	delete_command.add_argument("-t", "--type", help='Type of the disk ("CoreStorage" or "APFS"). Needed when using --uuid.')
	delete_command.add_argument("-p", "--password", help="Password of the disk.")

	replace_description = "Replaces an UUID."
	replace_command = subparsers.add_parser("replace", help=replace_description, description=replace_description)
	replace_command.add_argument("-o", "--old", help="Old value.")
	replace_command.add_argument("-n", "--new", help="New value.")

	uuid_description = "Returns the CoreStorage or APFS UUID of a volume."
	uuid_command = subparsers.add_parser("uuid", help=uuid_description, description=uuid_description)
	uuid_command.add_argument("-d", "--disk", help='Path to the disk, in the form "/dev/<disk>" or "/Volumes/<name>".')

	return parser.parse_args()


# Decrypts the disks saved
def decrypt_disks():
	# Gets the JSON (or, if it doesn't exists, an empty list)
	data = get_json_secure(passwords_path)

	# Decrypts all disks
	for dictionary in data:
		for uuid in dictionary.keys():
			password = dictionary[uuid][0]
			disk_type = dictionary[uuid][1]
			if disk_type == DISK_TYPE_CORESTORAGE:
				subprocess.run(["diskutil", "coreStorage", "unlockVolume", uuid, "-passphrase", password], check=True)
				subprocess.run(["diskutil", "mount",  uuid], check=True)
			elif disk_type == DISK_TYPE_APFS:
				subprocess.run(["diskutil", "apfs", "unlockVolume", uuid, "-passphrase", password], check=True)				


def add_disk(disk=None, uuid=None, disk_type=None, password=None):
	"""Tests and saves an UUID and password, to use them latter in decrypt_disks()."""

	# If the UUID or the password haven't been passed as arguments, request it.
	if uuid is None or disk_type is None:
		if disk is None:
			disk = input('Introduce the path to the disk to unlock: ')
		uuid, disk_type = get_uuid(disk)

	if password is None:
		password = getpass.getpass("Introduce password: ")

	# Gets the JSON (or, if it doesn't exists, an empty list)
	data = get_json_secure(passwords_path)

	# Checks if the UUID is already added to the JSON
	for dictionary in data:
		if uuid in dictionary.keys():
			print(
				'The UUID is already added to the JSON. Use "com.juanjonol.unlock.py replace" if you want to change it.')
			return

	# Test UUID and password before saving it
	try:
		# Try to unmount the disk. If it's successful or the disk wasn't mounted, the password can be tested.
		subprocess.run(['diskutil', 'unmount', uuid])
		if disk_type == DISK_TYPE_CORESTORAGE:
			subprocess.run(["diskutil", "coreStorage", "unlockVolume", uuid, "-passphrase", password], check=True)
		elif disk_type == DISK_TYPE_APFS:
			subprocess.run(["diskutil", "apfs", "unlockVolume", uuid, "-passphrase", password], check=True)
	except:
		# If the password is incorrect, the unlock will fail. The unlock will also fail if the disk was mounted but 
		# can't be unmounted, in which case the password can't be automatically tested as far as I know. 
		# Instead, ask the user again for the password and check that they match.
		print("The password couldn't be automatically checked.")
		password_verification = getpass.getpass("Please introduce the password for the disk again: ")
		if password_verification != password:
			print("ERROR: The passwords don't match.")
			return

	# Update the data in the JSON
	data.append({uuid: [password, disk_type]})
	write_json_secure(data, passwords_path)
	print("Added disk with UUID ", uuid)


# Deletes a UUID and his corresponding password
def delete_disk(disk=None, uuid=None, disk_type=None, password=None):
	# If the UUID or the password haven't been passed as arguments, request it.
	if uuid is None or disk_type is None:
		if disk is None:
			disk = input('Introduce the path to the disk to unlock: ')
		uuid, disk_type = get_uuid(disk)

	if password is None:
		password = getpass.getpass("Introduce password: ")

	# Gets the JSON (or, if it doesn't exists, an empty list)
	data = get_json_secure(passwords_path)

	# Checks if the UUID is already added to the JSON
	for dictionary in data:
		if uuid in dictionary.keys():
			# Deletes the UUID
			try:
				data.remove({uuid: [password, disk_type]})  # This just works if the uuid and the password match.
				os.remove(passwords_path)  # This shouldn't be needed (the file should be destroyed when writing in it).
				write_json_secure(data, passwords_path)
				print("Deleted disk with UUID ", uuid)
			except:
				print("ERROR: the disk with UUID %s couldn't be deleted. Check that the password is correct." %uuid)
			return

	# If the program reach this point, the UUID wasn't in the passwords file.
	print("The UUID is not saved, or the password for that UUID is incorrect.")


# Replaces an UUID.
def replace_value(old_value=None, new_value=None):
	# If the old or the new value haven't been passed as arguments, request it.
	if old_value is None:
		old_value = input("Introduce old value: ")

	if new_value is None:
		new_value = input("Introduce new value: ")

	# Gets the JSON (or, if it doesn't exists, an empty list)
	data = get_json_secure(passwords_path)

	for dictionary in data:
		for uuid in dictionary.keys():
			password = dictionary[uuid][0]
			disk_type = dictionary[uuid][1]
			if uuid == old_value:
				delete_disk(uuid=old_value, disk_type=disk_type, password=password)
				add_disk(uuid=new_value, disk_type=disk_type, password=password)
				print("Replaced UUID %s with UUID %s." % (old_value, new_value))
				return

	# It the program reach this point, the old_value wasn't in the file.
	print("The value given is not saved, so it can't be replaced.")

	
def get_uuid(disk=None):
	"""Returns the UUID and the type of disk for a CoreStorage or APFS volume."""

	# If the path hasn't been passed as argument, request it.
	if disk is None:
		disk = input('Introduce the path to the disk to unlock: ')

	try:
		command = ["diskutil", "info", disk]
		result = subprocess.run(command, stdout=subprocess.PIPE, check=True).stdout.decode("utf-8")
		pattern = re.compile('Disk / Partition UUID:\s*(\S*)')
		match = pattern.search(result)
		if match is None:
			raise AssertionError('UUID not found.')
		uuid = match.group(1)
		if 'HFS+' in result:
			disk_type = DISK_TYPE_CORESTORAGE
		elif 'APFS' in result:
			disk_type = DISK_TYPE_APFS
		else:
			raise AssertionError('Unsupported filesystem.')
		print(uuid)
		return uuid, disk_type
	except:
		print("The given path is neither a CoreStorage disk nor an APFS volume.")


# Returns the JSON string in the file on the given path, or an empty list if there isn't a file
def get_json_secure(file_path):
	path = pathlib.Path(file_path)
	if path.is_file():
		uid = path.stat().st_uid
		permissions = path.stat().st_mode
		# If the file is not owned by root, or someone other than root can write on it, something is very very wrong.
		if uid != 0 or (permissions & stat.S_IWGRP) or (permissions & stat.S_IWOTH):
			raise PermissionError("The passwords file at %s doesn't have the correct permissions." % str(path))
		try:
			with open(file_path, "r") as input:
				return json.loads(input.read())
		except json.JSONDecodeError:
			return []
	else:
		return []


# Writes a list as a JSON, in a file that can be read and write just for the current user.
def write_json_secure(data, file_path):

	folder_permissions = stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR # 0o700: Read, write and execute just for the current user
	file_permissions = stat.S_IRUSR | stat.S_IWUSR  # 0o600: Read and write just for the current user

	# If the folder where the files go doesn't exists, create it
	path = pathlib.Path(file_path)
	if not path.parent.is_dir():
		path.parent.mkdir(folder_permissions)

	# Saves the JSON
	with os.fdopen(os.open(file_path, os.O_WRONLY | os.O_CREAT, file_permissions), 'w') as output:
		print(json.dumps(data), file=output)


def exception_handler(exception_type, exception, traceback):
    """
    Hides the traceback of all unhandled exceptions.
    https://stackoverflow.com/questions/27674602/hide-traceback-unless-a-debug-flag-is-set/27674608#27674608
    """
    print("%s: %s" % (exception_type.__name__, exception))


if __name__ == '__main__':
	# Disable Traceback (to avoid leaking sensible data)
	# sys.tracebacklimit = 0  # Doesn't work in Python 3: https://bugs.python.org/issue12276
	sys.excepthook = exception_handler
	sys.exit(main())
