import json
from uuid import uuid4

import pytest

from app.services.scm_inventory_opening_service import parse_opening_target
from app.services.scm_prepared_material_service import parse_preparation_target
from app.services.scm_weighing_service import ScmWeighingLocalError, parse_scm_label_id


def _qr(qr_type, **values):
    return json.dumps({"v": 1, "type": qr_type, **values})


def test_cada_modulo_acepta_solo_el_contexto_qr_de_su_tarea():
    opening_id = str(uuid4())
    label_id = str(uuid4())
    opm_id = str(uuid4())

    opening_qr = _qr(
        "SCM_INVENTORY_OPENING_TARGET",
        opening_id=opening_id,
        material_scm_id=7,
        ubicacion_codigo="A-ENVA-MP-GEN",
    )
    preparation_qr = _qr(
        "SCM_PREPARATION_WEIGHT_TARGET",
        orden_preparacion_id=opm_id,
        tipo_uso="APORTE",
    )
    production_qr = _qr("SCM_MANGA_LABEL", label_id=label_id)

    assert parse_opening_target(opening_qr)["opening_id"] == opening_id
    assert parse_preparation_target(preparation_qr)["orden_preparacion_id"] == opm_id
    assert parse_scm_label_id(production_qr) == label_id

    with pytest.raises(ScmWeighingLocalError) as opening_error:
        parse_opening_target(preparation_qr)
    assert opening_error.value.code == "INVALID_OPENING_TARGET_QR"

    with pytest.raises(ScmWeighingLocalError) as preparation_error:
        parse_preparation_target(production_qr)
    assert preparation_error.value.code == "INVALID_PREPARATION_TARGET_QR"

    with pytest.raises(ScmWeighingLocalError) as production_error:
        parse_scm_label_id(opening_qr)
    assert production_error.value.code == "INVALID_SCM_QR"
