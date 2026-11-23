"""Builds the Weapon Forge enemy sprites in Blender.

The pixel data lives in ../index.html, between /*ENEMIES_START*/ and /*ENEMIES_END*/,
so the game and this file can never disagree. Run inside Blender:
    exec(open(r"<path>/art/build_enemies.py", encoding="utf-8").read())
It starts a NEW EMPTY FILE, then writes:
    art/sprites/<id>.png      one PNG per enemy (1 px = 1 game pixel)
    art/sprites/enemies_sheet.png
    art/forge_enemies.blend   one collection per enemy, pixel-sharp planes + ortho camera
"""
import json, os, re, bpy

ART = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else ART_DIR  # noqa: F821
ROOT = os.path.dirname(ART)
SPRITES = os.path.join(ART, "sprites")
PX = 0.1          # Blender units per sprite pixel
GAP = 8           # pixels between sprites in the scene / sheet

def load_enemies():
    html = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
    m = re.search(r"/\*ENEMIES_START\*/(.*?)/\*ENEMIES_END\*/", html, re.S)
    return json.loads(m.group(1))

def decode(row):
    out, n = [], ""
    for ch in row:
        if ch.isdigit(): n += ch
        else: out.append(ch * (int(n) if n else 1)); n = ""
    return "".join(out)

def expand(e):
    rows = [decode(r) for r in e["rows"]]
    if e["mirror"]: rows = [r + r[::-1] for r in rows]
    return rows

def hex_rgba(h):
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)] + [1.0]

def make_image(name, w, h, put):
    img = bpy.data.images.new(name, w, h, alpha=True)
    buf = [0.0] * (w * h * 4)
    put(buf, w, h)
    img.pixels.foreach_set(buf)
    img.update()
    return img

def paint(buf, bw, bh, e, rows, ox):
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch == ".": continue
            # Blender images are bottom-up; anchor sprites to the sheet's bottom edge
            i = ((len(rows) - 1 - y) * bw + ox + x) * 4
            buf[i:i + 4] = hex_rgba(e["pal"].get(ch, "#ff00ff"))

def save_png(img, path):
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()

def pixel_material(name, img):
    mat = bpy.data.materials.new(name)
    try: mat.use_nodes = True
    except Exception: pass
    nt = mat.node_tree
    nt.nodes.clear()
    tex = nt.nodes.new("ShaderNodeTexImage"); tex.image = img; tex.interpolation = "Closest"
    emit = nt.nodes.new("ShaderNodeEmission")
    clear = nt.nodes.new("ShaderNodeBsdfTransparent")
    mix = nt.nodes.new("ShaderNodeMixShader")
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(tex.outputs["Color"], emit.inputs["Color"])
    nt.links.new(tex.outputs["Alpha"], mix.inputs[0])
    nt.links.new(clear.outputs[0], mix.inputs[1])
    nt.links.new(emit.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])
    for n, x in ((tex, -600), (emit, -300), (clear, -300), (mix, -100), (out, 100)): n.location.x = x
    clear.location.y = 150
    return mat

def sprite_plane(name, w, h, mat, x0, coll):
    # standing in the XZ plane, origin at bottom-centre (where the sprite touches the ground)
    hw, hh = w * PX / 2, h * PX
    me = bpy.data.meshes.new(name)
    me.from_pydata([(-hw, 0, 0), (hw, 0, 0), (hw, 0, hh), (-hw, 0, hh)], [], [(0, 1, 2, 3)])
    uv = me.uv_layers.new(name="UVMap")
    for loop, co in zip(uv.data, [(0, 0), (1, 0), (1, 1), (0, 1)]): loop.uv = co
    me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    ob.location.x = x0
    coll.objects.link(ob)
    return ob

def build():
    enemies = load_enemies()
    report, problems = [], []
    for e in enemies:
        e["px"] = expand(e)
        w = len(e["px"][0])
        for y, r in enumerate(e["px"]):
            if len(r) != w: problems.append(f"{e['id']} row {y}: {len(r)} px, expected {w}")
    if problems:
        return {"ok": False, "problems": problems}

    bpy.ops.wm.read_homefile(use_empty=True)
    scene = bpy.context.scene
    scene.view_settings.view_transform = "Standard"
    os.makedirs(SPRITES, exist_ok=True)

    root = bpy.data.collections.new("Enemies")
    scene.collection.children.link(root)

    sheet_w = sum(len(e["px"][0]) for e in enemies) + GAP * (len(enemies) - 1)
    sheet_h = max(len(e["px"]) for e in enemies)
    total_w = sheet_w * PX
    x = -total_w / 2
    ox = 0
    sheet_jobs = []
    for e in enemies:
        rows = e["px"]; w, h = len(rows[0]), len(rows)
        img = make_image(f"enemy_{e['id']}", w, h, lambda b, bw, bh, e=e, rows=rows: paint(b, bw, bh, e, rows, 0))
        save_png(img, os.path.join(SPRITES, f"{e['id']}.png"))
        coll = bpy.data.collections.new(f"Enemy_{e['id'].capitalize()}")
        root.children.link(coll)
        ob = sprite_plane(f"{e['id']}_sprite", w, h, pixel_material(f"M_{e['id']}", img), x + w * PX / 2, coll)
        ob["enemy_name"] = e["name"]; ob["idle"] = e["idle"]; ob["size_px"] = f"{w}x{h}"
        sheet_jobs.append((e, rows, ox))
        report.append({"id": e["id"], "name": e["name"], "size": f"{w}x{h}", "collection": coll.name})
        x += (w + GAP) * PX; ox += w + GAP

    def paint_sheet(b, bw, bh):
        for e, rows, o in sheet_jobs: paint(b, bw, bh, e, rows, o)
    sheet = make_image("enemies_sheet", sheet_w, sheet_h, paint_sheet)
    save_png(sheet, os.path.join(SPRITES, "enemies_sheet.png"))

    # ground line + camera
    cam_data = bpy.data.cameras.new("Camera"); cam_data.type = "ORTHO"
    cam_data.ortho_scale = total_w + 2
    cam = bpy.data.objects.new("Camera", cam_data)
    cam.location = (0, -10, sheet_h * PX / 2)
    cam.rotation_euler = (1.5707963, 0, 0)
    scene.collection.objects.link(cam)
    scene.camera = cam
    scene.render.resolution_x = (sheet_w + 20) * 4
    scene.render.resolution_y = (sheet_h + 20) * 4
    scene.render.film_transparent = False
    world = bpy.data.worlds.new("World"); scene.world = world
    try:
        world.use_nodes = True
    except Exception:
        pass
    bg = world.node_tree.nodes.get("Background")
    if bg: bg.inputs[0].default_value = (0.03, 0.02, 0.025, 1)

    for img in list(bpy.data.images):
        if img.name.startswith("enemy") or img.name == "enemies_sheet":
            img.pack()
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(ART, "forge_enemies.blend"))
    return {"ok": True, "enemies": report, "sheet": f"{sheet_w}x{sheet_h}"}

result = build()
