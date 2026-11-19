import re
from xml.etree import ElementTree as ET

import pytest

from mesa_inventory_sticker import render_sticker


UNIT = dict(codigo="INV-000123", pieza="Base de regadera", color="Lila sólido",
            zona="Almacén de armado – 3.er piso", bruto="9.300", tara="1.500", neto="7.800")


@pytest.mark.parametrize("kind", ["identidad", "pesaje"])
def test_job_and_preview_identify_the_same_manga(kind):
    media = "50x50"
    tspl = render_sticker(UNIT, kind, media, "tspl")
    svg = ET.fromstring(render_sticker(UNIT, kind, media, "svg"))
    assert tspl.startswith("SIZE 109 mm, 50 mm\r\n")
    assert tspl.count("PRINT 1,1") == 1
    assert re.search(r'^QRCODE .*"INV-000123"\r?$', tspl, re.M)
    assert svg.attrib["width"] == ("50mm" if kind == "identidad" else "109mm")
    assert svg.attrib["height"] == "50mm"
    expected_copies = 1 if kind == "identidad" else 2
    assert tspl.count('QRCODE ') == expected_copies
    assert len(re.findall(r'^QRCODE .*"INV-000123"\r?$', tspl, re.M)) == expected_copies
    assert "INV-000123" in "".join(svg.itertext())
    assert ("7.800" in tspl) == (kind == "pesaje")
    assert ("7.800" in "".join(svg.itertext())) == (kind == "pesaje")


def test_unweighed_and_unknown_media_or_code():
    for unit, kind, media in [({"codigo": "INV-12"}, "pesaje", "50x50"),
                             (UNIT, "pesaje", "A4"),
                             ({**UNIT, "codigo": 'INV-1"\nPRINT 2'}, "identidad", "50x50")]:
        with pytest.raises(ValueError):
            render_sticker(unit, kind, media, "tspl")
    tspl = render_sticker({**UNIT, "pieza": 'ABC"\r\nPRINT 5,1'}, "pesaje", "50x50", "tspl")
    assert not re.search(r'^PRINT 5', tspl, re.M)


def test_prenumbered_identity_is_two_up_without_invented_measurements():
    job = render_sticker({"codigo": "INV-001"}, "identidad", "50x50", "tspl")
    preview = ET.fromstring(render_sticker({"codigo": "INV-001"}, "identidad", "50x50", "svg"))
    assert preview.attrib["viewBox"] == "24 0 400 400"
    assert preview.attrib["width"] == "50mm"
    assert preview.attrib["height"] == "50mm"
    assert job.count("QRCODE ") == 1
    assert len(re.findall(r'^QRCODE .*"INV-001"\r?$', job, re.M)) == 1
    assert "Neto" not in job and " kg" not in job and "None" not in job
    for x, y in re.findall(r"^(?:TEXT|QRCODE) (\d+),(\d+)", job, re.M):
        assert 24 <= int(x) < 424 and 0 <= int(y) < 400


def test_return_2up_uses_only_the_confirmed_net_weight():
    job = render_sticker({"codigo": "RET-001", "pieza": "Tapa", "color": "Azul", "neto": "2.125"}, "retorno", "50x50", "tspl")
    assert job.count("QRCODE ") == 2
    assert job.count("PRINT 1,1") == 1
    assert job.count("Neto 2.125 kg") == 2
    assert "Bruto" not in job and "Tara" not in job
