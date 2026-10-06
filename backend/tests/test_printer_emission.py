import sys

from app.services.printer_service import (
    PrinterEmissionResult,
    PrinterService,
)


class FakeWin32Print:
    def __init__(self, *, start_error=None, bytes_written=None, write_error=None):
        self.start_error = start_error
        self.bytes_written = bytes_written
        self.write_error = write_error
        self.closed = False
        self.payload = None

    def OpenPrinter(self, _name):
        return object()

    def StartDocPrinter(self, _handle, _level, _document):
        if self.start_error:
            raise self.start_error
        return 41

    def StartPagePrinter(self, _handle):
        return None

    def WritePrinter(self, _handle, data):
        self.payload = data
        if self.write_error:
            raise self.write_error
        return len(data) if self.bytes_written is None else self.bytes_written

    def EndPagePrinter(self, _handle):
        return None

    def EndDocPrinter(self, _handle):
        return None

    def ClosePrinter(self, _handle):
        self.closed = True


def _printer():
    printer = PrinterService(printer_type="TSPL", printer_name="TEST-TSC")
    printer._connected = True
    return printer


def test_start_doc_failure_is_safe_before_emission(monkeypatch):
    win32 = FakeWin32Print(start_error=RuntimeError("spooler unavailable"))
    monkeypatch.setitem(sys.modules, "win32print", win32)

    result = _printer().print_tspl_result("PRINT 1,1")

    assert result.status == PrinterEmissionResult.NOT_EMITTED
    assert result.document_started is False
    assert result.write_attempted is False
    assert win32.payload is None
    assert win32.closed is True


def test_partial_write_is_uncertain_and_reports_byte_count(monkeypatch):
    payload = "SIZE 109 mm, 50 mm\nPRINT 1,1"
    expected = len(payload.encode("utf-8"))
    win32 = FakeWin32Print(bytes_written=expected - 1)
    monkeypatch.setitem(sys.modules, "win32print", win32)

    result = _printer().print_tspl_result(payload)

    assert result.status == PrinterEmissionResult.UNCERTAIN
    assert result.expected_bytes == expected
    assert result.bytes_written == expected - 1
    assert result.document_started is True
    assert result.write_attempted is True
    assert bool(result) is False
    assert win32.closed is True


def test_write_exception_after_start_doc_is_uncertain(monkeypatch):
    win32 = FakeWin32Print(write_error=RuntimeError("USB disconnected"))
    monkeypatch.setitem(sys.modules, "win32print", win32)

    result = _printer().print_tspl_result("PRINT 1,1")

    assert result.status == PrinterEmissionResult.UNCERTAIN
    assert result.document_started is True
    assert result.write_attempted is True
    assert result.bytes_written is None


def test_full_write_and_document_close_is_accepted(monkeypatch):
    payload = "PRINT 1,1"
    win32 = FakeWin32Print()
    monkeypatch.setitem(sys.modules, "win32print", win32)

    result = _printer().print_tspl_result(payload)

    assert result.status == PrinterEmissionResult.ACCEPTED
    assert result.bytes_written == len(payload.encode("utf-8"))
    assert result.job_id == 41
    assert bool(result) is True
    assert win32.closed is True


def test_diagnostic_failure_after_enddoc_does_not_change_accepted(monkeypatch):
    win32 = FakeWin32Print()
    monkeypatch.setitem(sys.modules, 'win32print', win32)
    def broken_log(*args, **kwargs):
        raise UnicodeEncodeError('ascii', '\u2713', 0, 1, 'unsupported')
    monkeypatch.setattr('builtins.print', broken_log)
    result = _printer().print_tspl_result('PRINT 1,1')
    assert result.status == PrinterEmissionResult.ACCEPTED
    assert result.job_id == 41
    assert win32.closed
