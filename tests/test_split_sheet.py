"""forge split-sheet: a 2x2 sheet becomes 4 centred views at one shared scale."""

from PIL import Image, ImageDraw

from forge.cli import main
from forge.sheets import split_sheet


def _sheet(path, sizes, offset=(0, 0)):
    img = Image.new("RGB", (2048, 2048), (205, 205, 208))
    d = ImageDraw.Draw(img)
    for i, s in enumerate(sizes):
        cx = (i % 2) * 1024 + 512 + offset[0]
        cy = (i // 2) * 1024 + 512 + offset[1]
        if s:
            d.ellipse((cx - s // 2, cy - s, cx + s // 2, cy + s), fill=(150, 110, 40))
    img.save(path)
    return path


def test_split_sheet_same_scale_centred(tmp_path):
    sheet = _sheet(tmp_path / "bell.png", [300, 200, 300, 200], offset=(-150, 60))
    res = split_sheet(sheet, tmp_path / "views")
    assert [p.name for p in res.outputs] == ["bell_front.png", "bell_left.png", "bell_back.png", "bell_right.png"]
    assert not res.warnings
    sizes = {Image.open(p).size for p in res.outputs}
    assert len(sizes) == 1                                   # one scale for all views
    side = sizes.pop()[0]
    assert 600 < side < 800                                  # tallest object (600 px) + margin
    im = Image.open(res.outputs[1])
    assert im.getpixel((side // 2, side // 2)) == (150, 110, 40)   # re-centred
    assert im.getpixel((2, 2)) == (205, 205, 208)                  # clean background


def test_cli_folder_and_warnings(tmp_path, capsys):
    _sheet(tmp_path / "hair.png", [300, 300, 300, 300])
    _sheet(tmp_path / "rope.webp", [300, 0, 300, 300])       # one view missing
    assert main(["split-sheet", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "[OK] hair.png" in out and "[!] rope.webp" in out and "left: cell is empty" in out
    assert len(list((tmp_path / "views").glob("hair_*.png"))) == 4
    assert len(list((tmp_path / "views").glob("rope_*.png"))) == 3
