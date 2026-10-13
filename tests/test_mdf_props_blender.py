"""Blender checks for how MDF material properties are typed on import.

A one-value property whose name looks like a switch ("Use...", "..._or_...", "is...") used to
be imported as a checkbox whatever its value, so a real float came back as 0 or 1 on export:
MH Wilds UseCounterExposureEmit = 0.63 was written back as 1.0. A name match only means a bool
when the stored value is 0 or 1; names in boolPropertySet stay bools.

Run with Blender --background --factory-startup --python-exit-code 1 --python
tests/test_mdf_props_blender.py. Uses synthetic properties, never retail assets.
"""
import importlib
from pathlib import Path
import sys

import addon_utils
import bpy


def main():
	repo = Path(__file__).resolve().parents[1]
	sys.path.insert(0, str(repo.parent))
	addon_utils.enable(repo.name, default_set=True)
	mdf_io = importlib.import_module(repo.name + ".modules.mdf.blender_re_mdf")
	mdf_file = importlib.import_module(repo.name + ".modules.mdf.file_re_mdf")

	def prop(name, *values):
		p = mdf_file.Property()
		p.propName = name
		p.propValue = list(values)
		p.paramCount = len(values)
		return p

	cases = [
		# name, stored values, expected data_type, expected exported value
		("UseCounterExposureEmit", (0.63,), "FLOAT", 0.63),
		("UseEmissive", (1.0,), "BOOL", 1.0),
		("UseDetailMap", (0.0,), "BOOL", 0.0),
		("Mask_or_Alpha", (0.25,), "FLOAT", 0.25),
		("isDoubleSided", (1.0,), "BOOL", 1.0),
		("BackFaceNormalFilp", (1.0,), "BOOL", 1.0),
		("Roughness", (0.5,), "FLOAT", 0.5),
	]
	obj = bpy.data.objects.new("MDFPropChecks", None)
	bpy.context.scene.collection.objects.link(obj)
	mdf_io.addPropsToPropList(obj, [prop(name, *values) for name, values, _, _ in cases])
	items = {item.prop_name: item for item in obj.re_mdf_material.propertyList_items}
	for name, values, data_type, exported in cases:
		item = items[name]
		assert item.data_type == data_type, (name, values, item.data_type)
		value = mdf_io.getPropValue(item)
		assert len(value) == 1 and abs(value[0] - exported) < 1e-6, (name, values, list(value))
	print("PASS a switch-like name is a bool only when its value is 0 or 1 "
		"(UseCounterExposureEmit 0.63 exports as 0.63)", flush=True)


if __name__ == "__main__":
	main()
