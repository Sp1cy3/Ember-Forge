"""Builds the Weapon Forge weapon sprites in Blender.

The pixel data lives in ../index.html, between /*WEAPONS_START*/ and /*WEAPONS_END*/,
so the game and this file can never disagree.

Run inside Blender (starts a NEW EMPTY FILE):
    g = {"ART_DIR": r"<path>/art"}; exec(open(g["ART_DIR"] + "/build_weapons.py", encoding="utf-8").read(), g)
Writes:
    art/sprites/weapons/<weapon>_<n>_<part>.png   each stacking part (1 px = 1 game pixel)
    art/sprites/weapons/<weapon>.png              the assembled weapon
    art/sprites/weapons/weapons_sheet.png         all three side by side
    art/forge_weapons.blend   one collection per weapon; each part is its own plane, parented to an empty
"""
import json, os, re, bpy

ART = ART_DIR  # noqa: F821  (passed in by the caller)
OUT = os.path.join(ART, "sprites", "weapons")
PX = 0.1   # Blender units per sprite pixel
GAP = 10   # pixels between weapons

def decode(row):
    out, n = [], ""
    for ch in row:
        if ch.isdigit(): n += ch
        else: out.append(ch * (int(n) if n else 1)); n = ""
    return "".join(out)

def expand(rows, mirror):
    """Decodes rows; "28*<row>" repeats a row, mirror appends the reversed half."""
    out = []
    for r in rows:
        m = re.match(r"^(\d+)\*(.*)$", r)
        s = decode(m.group(2) if m else r)
        if mirror: s += s[::-1]
        out += [s] * (int(m.group(1)) if m else 1)
    return out

def load_weapons():
    html = open(os.path.join(os.path.dirname(ART), "index.html"), encoding="utf-8").read()
    return json.loads(re.search(r"/\*WEAPONS_START\*/(.*?)/\*WEAPONS_END\*/", html, re.S).group(1))

def hex_rgba(h):
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)] + [1.0]

def slug(s): return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")

def new_image(name, w, h, blits, pal):
    """blits: list of (rows, x, y_top) painted into a w*h image (y_top measured from the image top)."""
    img = bpy.data.images.new(name, w, h, alpha=True)
    buf = [0.0] * (w * h * 4)
    for rows, ox, oy in blits:
        for y, row in enumerate(rows):
            for x, ch in enumerate(row):
                if ch == ".": continue
                i = ((h - 1 - (oy + y)) * w + ox + x) * 4
                buf[i:i + 4] = hex_rgba(pal.get(ch, "#ff00ff"))
    img.pixels.foreach_set(buf)
    img.update()
    return img

def save_png(img, path):
    img.filepath_raw = path; img.file_format = "PNG"; img.save()

def pixel_material(name, img):
    mat = bpy.data.materials.new(name)
    try: mat.use_nodes = True
    except Exception: pass
    nt = mat.node_tree; nt.nodes.clear()
    tex = nt.nodes.new("ShaderNodeTexImage"); tex.image = img; tex.interpolation = "Closest"
    emit = nt.nodes.new("ShaderNodeEmission"); clear = nt.nodes.new("ShaderNodeBsdfTransparent")
    mix = nt.nodes.new("ShaderNodeMixShader"); out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(tex.outputs["Color"], emit.inputs["Color"])
    nt.links.new(tex.outputs["Alpha"], mix.inputs[0])
    nt.links.new(clear.outputs[0], mix.inputs[1])
    nt.links.new(emit.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])
    for n, x in ((tex, -600), (emit, -300), (clear, -300), (mix, -100), (out, 100)): n.location.x = x
    clear.location.y = 150
    return mat

def plane(name, w, h, mat, coll):
    """Upright quad in the XZ plane, origin at its bottom-centre."""
    hw, hh = w * PX / 2, h * PX
    me = bpy.data.meshes.new(name)
    me.from_pydata([(-hw, 0, 0), (hw, 0, 0), (hw, 0, hh), (-hw, 0, hh)], [], [(0, 1, 2, 3)])
    uv = me.uv_layers.new(name="UVMap")
    for loop, co in zip(uv.data, [(0, 0), (1, 0), (1, 1), (0, 1)]): loop.uv = co
    me.materials.append(mat)
    ob = bpy.data.objects.new(name, me); coll.objects.link(ob)
    return ob

def build():
    data = load_weapons()
    pal, weapons = data["pal"], data["weapons"]
    problems = []
    for wp in weapons:
        for i, p in enumerate(wp["parts"]):
            rows = expand(p["rows"], p.get("mirror", False))
            p["px"] = rows
            for y, r in enumerate(rows):
                if len(r) != len(rows[0]): problems.append(f"{wp['id']} part {i} ({p['name']}) row {y}: {len(r)} px, expected {len(rows[0])}")
            if len(rows[0]) % 2: problems.append(f"{wp['id']} part {i} ({p['name']}) is {len(rows[0])} px wide; keep widths even so parts centre on whole pixels")
        wp["w"] = max(len(p["px"][0]) for p in wp["parts"])
        wp["h"] = sum(len(p["px"]) for p in wp["parts"])
    if problems: return {"ok": False, "problems": problems}

    bpy.ops.wm.read_homefile(use_empty=True)
    scene = bpy.context.scene
    scene.view_settings.view_transform = "Standard"
    os.makedirs(OUT, exist_ok=True)
    root = bpy.data.collections.new("Weapons"); scene.collection.children.link(root)

    sheet_w = sum(wp["w"] for wp in weapons) + GAP * (len(weapons) - 1)
    sheet_h = max(wp["h"] for wp in weapons)
    x_px, report, sheet_blits = 0, [], []
    for wp in weapons:
        coll = bpy.data.collections.new(f"Weapon_{wp['id'].capitalize()}"); root.children.link(coll)
        empty = bpy.data.objects.new(wp["id"], None); empty.empty_display_type = "SINGLE_ARROW"
        empty.location = ((x_px + wp["w"] / 2 - sheet_w / 2) * PX, 0, 0); coll.objects.link(empty)
        empty["weapon_name"] = wp["name"]
        z_px, blits, parts = 0, [], []
        for n, p in enumerate(wp["parts"], 1):
            rows = p["px"]; w, h = len(rows[0]), len(rows)
            nm = f"{wp['id']}_{n}_{slug(p['name'])}"
            img = new_image(nm, w, h, [(rows, 0, 0)], pal)
            save_png(img, os.path.join(OUT, nm + ".png"))
            ob = plane(nm, w, h, pixel_material("M_" + nm, img), coll)
            ob.parent = empty; ob.location = (0, 0, z_px * PX)
            ob["part_name"] = p["name"]; ob["slot"] = n; ob["size_px"] = f"{w}x{h}"
            # assembled image: parts stacked bottom-up, centred
            blits.append((rows, (wp["w"] - w) // 2, wp["h"] - z_px - h))
            sheet_blits.append((rows, x_px + (wp["w"] - w) // 2, sheet_h - z_px - h))
            parts.append(f"{p['name']} {w}x{h}")
            z_px += h
        save_png(new_image(wp["id"], wp["w"], wp["h"], blits, pal), os.path.join(OUT, wp["id"] + ".png"))
        report.append({"weapon": wp["name"], "size": f"{wp['w']}x{wp['h']}", "parts": parts})
        x_px += wp["w"] + GAP
    save_png(new_image("weapons_sheet", sheet_w, sheet_h, sheet_blits, pal), os.path.join(OUT, "weapons_sheet.png"))

    cam_data = bpy.data.cameras.new("Camera"); cam_data.type = "ORTHO"
    cam_data.ortho_scale = (sheet_h + 16) * PX
    cam = bpy.data.objects.new("Camera", cam_data)
    cam.location = (0, -10, sheet_h * PX / 2); cam.rotation_euler = (1.5707963, 0, 0)
    scene.collection.objects.link(cam); scene.camera = cam
    scene.render.resolution_x = (sheet_w + 40) * 4
    scene.render.resolution_y = (sheet_h + 16) * 4
    world = bpy.data.worlds.new("World"); scene.world = world
    try: world.use_nodes = True
    except Exception: pass
    bg = world.node_tree.nodes.get("Background")
    if bg: bg.inputs[0].default_value = (0.03, 0.02, 0.025, 1)

    for img in bpy.data.images:
        if img.size[0]: img.pack()
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(ART, "forge_weapons.blend"))
    return {"ok": True, "weapons": report, "sheet": f"{sheet_w}x{sheet_h}"}

result = build()
