"""Connections shown on the Employee form."""


def employee_dashboard(data):
	"""Assets (laptops, mobiles ...) handed to the employee: the Asset's Custodian is the employee.

	The count only shows for users who may read Assets (Store, IT); HR Manager does not see it unless
	somebody gives that role read access to Asset.
	"""
	data.setdefault("non_standard_fieldnames", {})["Asset"] = "custodian"
	data.setdefault("transactions", []).append({"label": "Assets", "items": ["Asset"]})
	return data
