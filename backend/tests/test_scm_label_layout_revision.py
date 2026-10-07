from copy import deepcopy
import re

import pytest

from app.services.scm_prelabel_service import ScmPrelabelService
from test_scm_prelabels import _color_work_label, _post_weighing_label


@pytest.mark.parametrize('numbers', [(2,), (2, 999)])
def test_distinct_native_prelabels_preserve_sources_and_blank_odd_slot(numbers):
    labels = [_color_work_label(f'OF-DEMO-OT007-M{n:03}') for n in numbers]
    before = deepcopy(labels)
    service = ScmPrelabelService()
    tspl = service.generate_tspl({'labels': labels})
    svg = service.generate_preview_svg({'labels': labels})
    assert labels == before
    assert tspl.count('PRINT 1,1') == 1
    assert tspl.count('QRCODE ') == len(numbers)
    for n, label in zip(numbers, labels):
        assert tspl.count(label['payload']['qr']['label_id']) == 1
        assert f'"2",0,3,6,"{n}"' in tspl
    assert 'Arial' not in tspl and 'Courier' not in tspl and 'BITMAP' not in tspl
    assert set(re.findall(r'TEXT \d+,\d+,"0",0,(\d+),(\d+)', tspl)) == {('6', '6')}
    assert 'width="109mm" height="50mm"' in svg
    if len(numbers) == 1:
        for line in tspl.splitlines():
            if line.startswith(('TEXT ', 'QRCODE ', 'BAR ', 'BOX ')):
                assert int(line.split(' ', 1)[1].split(',')[0]) < service.RIGHT_X


def test_duplicate_pre_manga_or_qr_is_rejected_before_render():
    first = _color_work_label('OF-DEMO-OT007-M002')
    second = _color_work_label('OF-DEMO-OT007-M002')
    service = ScmPrelabelService()
    with pytest.raises(ValueError, match='diferentes'):
        service.generate_tspl({'labels': [first, second]})
    second['payload']['codigo_manga'] = 'OF-DEMO-OT007-M003'
    second['payload']['qr'] = deepcopy(first['payload']['qr'])
    with pytest.raises(ValueError, match='diferentes'):
        service.generate_preview_svg({'labels': [first, second]})


def test_post_piece_name_immediately_above_net_without_catalog_id_or_source_mutation():
    label = _post_weighing_label('OF-DEMO-OT007-M002')
    label['payload'].pop('pieza', None)
    label['payload']['pieza_color'] = 'TOLVA MUESTRA ROJO (PC-000073)'
    before = deepcopy(label)
    service = ScmPrelabelService()
    tspl = service.generate_tspl({'labels': [label]})
    svg = service.generate_preview_svg({'labels': [label]})
    assert label == before
    assert 'PC-000073' not in tspl and 'PC-000073' not in svg
    assert 'TEXT 32,78,"1",0,1,1,"TOLVA MUESTRA ROJO"\nTEXT 32,100,"2",0,1,1,"PESO NETO FINAL (kg)"' in tspl
    assert svg.index('TOLVA MUESTRA ROJO') < svg.index('PESO NETO FINAL')
    assert 'QRCODE' not in tspl


def test_only_catalog_suffix_removed_not_name_parentheses():
    assert ScmPrelabelService._piece_name({'pieza_color': 'TOLVA (GRANDE) ROJO (PC-000073)'}) == 'TOLVA (GRANDE) ROJO'
    assert ScmPrelabelService._piece_name({'pieza_color': 'TOLVA (GRANDE)'}) == 'TOLVA (GRANDE)'


@pytest.mark.parametrize('sku', ['P-01', 'PT-DEMO-AP', 'PC-000073'])
def test_historical_catalog_sku_families_are_not_printed(sku):
    assert ScmPrelabelService._piece_name({'pieza_color': f'TOLVA (GRANDE) ({sku})'}) == 'TOLVA (GRANDE)'


def test_explicit_sku_removes_only_exact_suffix_even_for_other_catalog_families():
    assert ScmPrelabelService._piece_name({'pieza_color': 'TOLVA (GRANDE) (ART.12)', 'pieza_color_sku': 'ART.12'}) == 'TOLVA (GRANDE)'


def test_mixed_pre_post_job_cannot_reintroduce_duplicate_prelabels():
    with pytest.raises(ValueError, match='No mezclar'):
        ScmPrelabelService().generate_tspl({'labels': [
            _color_work_label('OF-DEMO-OT007-M002'),
            _post_weighing_label('OF-DEMO-OT007-M003'),
        ]})


@pytest.mark.parametrize('value', ['4.150', '12345.67'])
def test_post_contribution_uses_freed_row_and_stays_inside_native_cell_geometry(value):
    label = _post_weighing_label('OF-DEMO-OT007-M002')
    label['payload'].pop('pieza', None)
    label['payload']['aporte_desde_control_anterior_kg'] = value
    tspl = ScmPrelabelService().generate_tspl({'labels': [label]})
    matches = re.findall(r'TEXT (\d+),264,"4",0,1,1,"([^\"]+)"', tspl)
    assert len(matches) == 2
    for (left, text), origin in zip(matches, (24, 464)):
        assert int(left) + len(text) * 24 == origin + 392
    assert 264 + 32 < 300  # Native font4 row does not collide with count.


def test_structured_post_prints_explicit_pz_and_color_in_font2_without_footer():
    label = _post_weighing_label("OF-DEMO-OT007-M002")
    label["payload"]["pieza"] = "TOLVA MUESTRA"
    label["payload"]["color"] = "ROJO SOLIDO"
    service = ScmPrelabelService()

    tspl = service._weight_column(24, label, "07/10/2026 11:00")
    svg = service._svg_weight_column(24, label, "07/10/2026 11:00")

    assert 'TEXT 32,78,"2",0,1,1,"PZ: TOLVA MUESTRA"' in tspl
    assert 'TEXT 32,100,"2",0,1,1,"COLOR: ROJO SOLIDO"' in tspl
    assert 'TEXT 32,122,"2",0,1,1,"PESO NETO FINAL (kg)"' in tspl
    assert "SIN QR" not in tspl
    assert 'font-size="20"' in svg
    assert "PZ: TOLVA MUESTRA" in svg
    assert "COLOR: ROJO SOLIDO" in svg
    assert "SIN QR" not in svg


def test_structured_post_wraps_without_truncating_and_keeps_worst_case_inside_label():
    label = _post_weighing_label("OF-DEMO-OT007-M002")
    label["payload"]["pieza"] = "BASE DE ORGANIZADOR DE MUESTRA EXTRA GRANDE"
    label["payload"]["color"] = "ROJO SOLIDO DE MUESTRA"
    service = ScmPrelabelService()

    tspl = service._weight_column(24, label, "07/10/2026 11:00")
    svg = service._svg_weight_column(24, label, "07/10/2026 11:00")

    assert 'PZ: BASE DE ORGANIZADOR DE' in tspl
    assert '  MUESTRA EXTRA GRANDE' in tspl
    assert 'COLOR: ROJO SOLIDO DE MUESTRA' in tspl
    assert 'PZ: BASE DE ORGANIZADOR DE' in svg
    assert 'MUESTRA EXTRA GRANDE' in svg
    assert 'COLOR: ROJO SOLIDO DE MUESTRA' in svg
    assert "..." not in tspl
    assert 'TEXT 32,243,"3"' not in tspl
    assert 'BAR 32,243,384,2' in tspl
    assert 'TEXT 32,362,"1"' in tspl

    label["payload"]["color"] = "ROJO SOLIDO DE MUESTRA EXTRA"
    worst_case_tspl = service._weight_column(24, label, "07/10/2026 11:00")
    assert 'COLOR: ROJO SOLIDO DE MUESTRA' in worst_case_tspl
    assert '  EXTRA' in worst_case_tspl
    assert 'BAR 32,265,384,2' in worst_case_tspl
    assert 'TEXT 32,384,"1"' in worst_case_tspl


def test_structured_post_rejects_unbreakable_or_overlong_identity_instead_of_dropping_it():
    label = _post_weighing_label("OF-DEMO-OT007-M002")
    service = ScmPrelabelService()
    label["payload"]["pieza"] = "X" * 40
    with pytest.raises(ValueError, match="Campo PZ"):
        service._weight_column(24, label, "07/10/2026 11:00")

    label["payload"]["pieza"] = "UNO DOS TRES CUATRO CINCO SEIS SIETE OCHO NUEVE DIEZ"
    label["payload"]["color"] = "UNO DOS TRES CUATRO CINCO SEIS SIETE OCHO NUEVE DIEZ"
    with pytest.raises(ValueError, match="Identidad PZ/COLOR"):
        service._weight_column(24, label, "07/10/2026 11:00")


def test_historical_post_without_pieza_does_not_infer_pz_or_color_from_pieza_color():
    label = _post_weighing_label("OF-DEMO-OT007-M002")
    label["payload"].pop("pieza", None)
    label["payload"]["pieza_color"] = "TOLVA MUESTRA ROJO (PC-000073)"
    tspl = ScmPrelabelService()._weight_column(24, label, "07/10/2026 11:00")

    assert "PZ:" not in tspl
    assert "COLOR:" not in tspl
    assert "TOLVA MUESTRA ROJO" in tspl
    assert "SIN QR" not in tspl
