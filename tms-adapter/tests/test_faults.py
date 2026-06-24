from app.tms.faults import TMSFault, TMSFaultError, complete_lines, find_terminal


def test_find_terminal_end_with_crlf():
    assert find_terminal(b"LOAD_ID:LD1   \r\nEND\r\n") == "end"


def test_find_terminal_end_without_crlf_is_not_terminal_midstream():
    # Strict: a bare END not yet CRLF-delimited and not at EOF -> keep reading.
    assert find_terminal(b"LOAD_ID:LD1   \r\nEND") is None


def test_find_terminal_end_without_crlf_is_terminal_at_eof():
    assert find_terminal(b"LOAD_ID:LD1   \r\nEND", at_eof=True) == "end"


def test_find_terminal_err():
    assert find_terminal(b"ERR|CODE:NOT_FOUND|MSG:nope\r\n") == "err"


def test_find_terminal_none_for_record_only():
    assert find_terminal(b"LOAD_ID:LD1   \r\n") is None


def test_find_terminal_none_for_partial_record():
    assert find_terminal(b"LOAD_ID:LD1") is None


def test_complete_lines_excludes_in_progress_tail():
    assert complete_lines(b"a\r\nb\r\nc") == [b"a", b"b"]


def test_complete_lines_at_eof_includes_tail():
    assert complete_lines(b"a\r\nb\r\nc", at_eof=True) == [b"a", b"b", b"c"]


def test_fault_error_http_status():
    assert TMSFaultError(TMSFault.TIMEOUT).http_status == 504
    assert TMSFaultError(TMSFault.PARTIAL).http_status == 502
    assert TMSFaultError(TMSFault.MALFORMED).http_status == 502
    assert TMSFaultError(TMSFault.CONNECT_ERROR).http_status == 502
