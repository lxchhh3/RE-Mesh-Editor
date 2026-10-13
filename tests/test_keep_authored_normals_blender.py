"""Per-key "Keep Authored Normals" for Wilds KEEPNORMALS shape key export.

KEEPNORMALS rows store each key's own normal next to its position delta. By default that normal is
the authored row normal turned by the key's deformation (the evaluated corner normal's basis -> key
turn). A key flagged "Keep Authored Normals" stores the authored row normal unchanged instead, so a
toon face lit by its authored normals stays lit that way under the key (a puffed cheek is not shaded
as a puff), and overlay geometry unfolding from a collapsed rest keeps the normals it was authored
with.

Checks, on a synthetic 3x3 grid whose centre vertex rises under two keys with identical deltas:
  - the toggle operator turns the flag on and off for the active key;
  - unflagged "Bend" stores turned normals (some row differs from the vertex's own normal);
  - flagged "Keep" stores every row's normal exactly equal to the vertex's own normal;
  - both keys keep identical position deltas.
The per-key normal half of each 8-byte keep-normals row is read from the raw payload (the importer
drops it), mapped to vertices through the target's sub-mesh entries the way re_mesh_parse does.

Run with Blender --background --factory-startup --python-exit-code 1 --python
tests/test_keep_authored_normals_blender.py. Uses a synthetic mesh, never retail assets.
"""
import importlib
from pathlib import Path
import sys
import tempfile

import addon_utils
import bpy
import numpy as np


def stored_key_normals(parse, reMesh, raw):
	"""{key name: {vertex index: (x, y, z) int8}} from LOD0's keep-normals second rows."""
	words = np.frombuffer(raw[:(len(raw) // 4) * 4], dtype="<u4")
	second = words[1::2]
	blendData = reMesh.blendShapeHeader.blendShapeList[0]
	out = {}
	payloadCursor = 0
	for target in list(blendData.blendTargetList)[:int(blendData.targetCount)]:
		channelCount = int(getattr(target, "blendShapeNum", 0) or 0)
		entries = list(getattr(target, "subMeshEntryList", []) or [])
		rowCount = sum(int(e.vertCount) for e in entries) if entries else int(target.vertCount)
		explicit = any(int(getattr(e, "vertOffset", 0) or 0) != 0 for e in entries)
		for channel in range(channelCount):
			remap = int(getattr(target, "blendSSIndex", 0) or 0) + channel
			name = reMesh.rawNameList[reMesh.blendShapeNameRemapList[remap]]
			rows = out.setdefault(name, {})
			running = 0
			for entry in entries:
				start = (int(entry.vertOffset) + channel * rowCount if explicit
						 else payloadCursor + channel * rowCount + running)
				for i in range(int(entry.vertCount)):
					word = int(second[start + i])
					byte = [(word >> (8 * b)) & 0xFF for b in range(3)]
					rows[int(entry.subMeshVertexStartIndex) + i] = tuple(v - 256 if v >= 128 else v for v in byte)
				running += int(entry.vertCount)
		payloadCursor += rowCount * channelCount
	return out


def main():
	repo = Path(__file__).resolve().parents[1]
	sys.path.insert(0, str(repo.parent))
	addon_utils.enable(repo.name, default_set=True)
	mesh_io = importlib.import_module(repo.name + ".modules.mesh.blender_re_mesh")
	parse = importlib.import_module(repo.name + ".modules.mesh.re_mesh_parse")
	codec = importlib.import_module(repo.name + ".modules.mesh.file_re_mesh")

	collection = bpy.data.collections.new("KeepAuthoredNormals")
	bpy.context.scene.collection.children.link(collection)
	data = bpy.data.meshes.new("grid")
	verts = [(x, y, 0.0) for y in (0, 1, 2) for x in (0, 1, 2)]
	faces = []
	for y in range(2):
		for x in range(2):
			a = y * 3 + x
			faces += [(a, a + 1, a + 4), (a, a + 4, a + 3)]
	data.from_pydata(verts, [], faces)
	data.update()
	data.polygons.foreach_set("use_smooth", [True] * len(data.polygons))
	data.normals_split_custom_set([(0, 0, 1)] * len(data.loops))
	uv = data.uv_layers.new(name="UVMap")
	for loop in data.loops:
		co = verts[loop.vertex_index]
		uv.data[loop.index].uv = (co[0] / 2, co[1] / 2)
	data.materials.append(bpy.data.materials.new("KeepMaterial"))
	obj = bpy.data.objects.new("LOD_0_Group_0_Sub_0__KeepMaterial", data)
	collection.objects.link(obj)
	obj.shape_key_add(name="Basis")
	for name in ("Bend", "Keep"):
		key = obj.shape_key_add(name=name)
		key.data[4].co.z = 0.5
		key.value = 0.0

	# the panel toggle works on the active key; the helpers are what export reads
	bpy.context.view_layer.objects.active = obj
	obj.active_shape_key_index = list(data.shape_keys.key_blocks).index(data.shape_keys.key_blocks["Keep"])
	keep_key = data.shape_keys.key_blocks["Keep"]
	assert not mesh_io.keepsAuthoredNormals(data, keep_key)
	assert bpy.ops.re_mesh.toggle_keep_authored_normals() == {"FINISHED"}
	assert mesh_io.keepsAuthoredNormals(data, keep_key)
	assert bpy.ops.re_mesh.toggle_keep_authored_normals() == {"FINISHED"}
	assert not mesh_io.keepsAuthoredNormals(data, keep_key)
	assert bpy.ops.re_mesh.toggle_keep_authored_normals() == {"FINISHED"}
	assert mesh_io.keepsAuthoredNormals(data, keep_key)
	assert not mesh_io.keepsAuthoredNormals(data, data.shape_keys.key_blocks["Bend"])
	print("PASS Keep Authored Normals toggles per active shape key", flush=True)

	options = dict(
		targetCollection=collection.name, selectedOnly=False, exportAllLODs=False,
		exportBlendShapes=True, blendShapeExportMode=-1, rotate90=False,
		useBlenderMaterialName=True, preserveBoneMatrices=False, exportBoundingBoxes=False,
		autoSolveRepeatedUVs=False, preserveSharpEdges=False, splitLoopVertices=True,
		normalizeWeights=True)
	with tempfile.TemporaryDirectory(prefix="keep-authored-normals-") as temporary:
		output = Path(temporary) / "keep.mesh.241111606"
		assert mesh_io.exportREMeshFile(str(output), options)
		reMesh = codec.readREMesh(str(output))
		assert int(reMesh.fileHeader.normalRecalcOffset) == 0   # the keep-normals layout
		captured = []
		original_reader = parse.ReadBlendShapeType7Buffer

		def capturing_reader(buffer, tags):
			captured.append(bytes(buffer))
			return original_reader(buffer, tags)

		parse.ReadBlendShapeType7Buffer = capturing_reader
		try:
			parsed = parse.ParsedREMesh()
			parsed.ParseREMesh(reMesh, {"importBlendShapes": True})
		finally:
			parse.ReadBlendShapeType7Buffer = original_reader
		assert captured, "no blend shape payload was read"
		submesh = parsed.mainMeshLODList[0].visconGroupList[0].subMeshList[0]
		own = {i: tuple(int(c) for c in np.rint(np.asarray(n) * 127)) for i, n in enumerate(submesh.normalList)}
		rows = stored_key_normals(parse, reMesh, captured[0])
		assert set(rows) >= {"Bend", "Keep"}, rows.keys()
		turned = [i for i, n in rows["Bend"].items() if any(abs(a - b) > 1 for a, b in zip(n, own[i]))]
		assert turned, "unflagged Bend should store normals turned by the bend"
		changed = {i: (n, own[i]) for i, n in rows["Keep"].items() if n != own[i]}
		assert not changed, changed
		deltas = {k.blendShapeName: np.asarray(k.deltas) for k in submesh.blendShapeList}
		assert np.allclose(deltas["Bend"], deltas["Keep"], atol=1e-4)
		print(f"PASS flagged key stores its rows' authored normals ({len(rows['Keep'])} rows); "
			  f"unflagged key turns them ({len(turned)} of {len(rows['Bend'])} rows)", flush=True)


if __name__ == "__main__":
	main()
