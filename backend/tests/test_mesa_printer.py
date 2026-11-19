import sys
import types

import pytest

from mesa_pilot import create_app
from mesa_printer import MesaPrinterService, PrinterEmissionUncertain, PrinterUnavailable


class FakeWin32:
    PRINTER_ENUM_LOCAL = 2
    PRINTER_ENUM_CONNECTIONS = 4

    def __init__(self, *, fail_write=False):
        self.fail_write = fail_write
        self.calls = []

    def EnumPrinters(self, _flags, name, level):
        self.calls.append("enum")
        return [self.GetPrinter(None, 2)]

    def GetPrinter(self, handle, level):
        return {"pPrinterName": "TSC-ESTACION-2", "Status": 0, "Attributes": 0}

    def OpenPrinter(self, name):
        self.calls.append(("open", name))
        if name != "TSC-ESTACION-2":
            raise OSError("not found")
        return "HANDLE"

    def StartDocPrinter(self, handle, level, doc):
        self.calls.append(("doc", handle, level, doc))

    def StartPagePrinter(self, handle):
        self.calls.append(("page", handle))

    def WritePrinter(self, handle, payload):
        self.calls.append(("write", handle, payload))
        if self.fail_write:
            raise OSError("spooler reset")
        return len(payload)

    def EndPagePrinter(self, handle):
        self.calls.append(("end-page", handle))

    def EndDocPrinter(self, handle):
        self.calls.append(("end-doc", handle))

    def ClosePrinter(self, handle):
        self.calls.append(("close", handle))


def test_service_requires_explicit_windows_queue():
    service = MesaPrinterService(FakeWin32())
    with pytest.raises(PrinterUnavailable):
        service.print_tspl("SIZE 109 mm, 50 mm\r\nPRINT 1,1", "")


def test_virtual_and_offline_queues_cannot_receive_tspl():
    for details in [{"pPrinterName": "Microsoft Print to PDF"},
                    {"pPrinterName": "TSC", "Status": 0x80}, {"pDriverName": "TSC", "Attributes": 0x400}]:
        driver = FakeWin32()
        driver.GetPrinter = lambda *args: details
        assert not MesaPrinterService(driver).available_printers()
        with pytest.raises(PrinterUnavailable):
            MesaPrinterService(driver).print_tspl("PRINT 1,1", "TSC-ESTACION-2")
        assert not any(call[0] == "doc" for call in driver.calls if isinstance(call, tuple))


def test_service_sends_one_2up_job_to_selected_queue():
    driver = FakeWin32()
    result = MesaPrinterService(driver).print_tspl("SIZE 109 mm, 50 mm\r\nPRINT 1,1", "TSC-ESTACION-2")
    assert result == {"status": "QUEUED", "printer_name": "TSC-ESTACION-2"}
    assert [call[0] for call in driver.calls if isinstance(call, tuple)] == ["open", "doc", "page", "write", "end-page", "end-doc", "close"]


def test_write_failure_is_uncertain_and_not_reported_as_success():
    with pytest.raises(PrinterEmissionUncertain):
        MesaPrinterService(FakeWin32(fail_write=True)).print_tspl("PRINT 1,1", "TSC-ESTACION-2")


def test_short_write_is_uncertain():
    driver = FakeWin32()
    driver.WritePrinter = lambda handle, payload: len(payload) - 1
    with pytest.raises(PrinterEmissionUncertain):
        MesaPrinterService(driver).print_tspl("PRINT 1,1", "TSC-ESTACION-2")


def test_status_without_win32_driver_has_no_false_connected_signal(tmp_path):
    app = create_app(tmp_path / "mesa.sqlite3")
    app.extensions["mesa_printer_service"] = MesaPrinterService(types.SimpleNamespace(
        EnumPrinters=lambda _flags: [],
        PRINTER_ENUM_LOCAL=2,
        PRINTER_ENUM_CONNECTIONS=4,
    ))
    response = app.test_client().get("/api/mesa/printer/status")
    assert response.status_code == 200
    assert response.get_json()["connected"] is False
    assert response.get_json()["available"] == []


def test_central_label_source_is_used_and_identity_prints_one_copy(tmp_path):
    class Central:
        def __init__(self):
            self.calls = []

        def label(self, code, area):
            self.calls.append((code, area))
            return {"codigo": code, "pieza": "Tapa", "color": "Azul", "zona": "C66", "bruto": None, "tara": None, "neto": None}

    central = Central()
    app = create_app(tmp_path / "mesa.sqlite3")
    app.extensions["mesa_central"] = central
    app.extensions["mesa_printer_service"] = MesaPrinterService(FakeWin32())
    response = app.test_client().post(
        "/api/mesa/inventario/etiquetas/INV-CENTRAL/identidad/print",
        json={"printer_name": "TSC-ESTACION-2"},
    )
    assert response.status_code == 202
    assert response.get_json()["copies"] == 1
    assert central.calls == [("INV-CENTRAL", "inventario")]

