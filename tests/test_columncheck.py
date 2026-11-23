"""Tests for columncheck."""

import json

import pytest

from columncheck import Problem, lint_csv, sniff_delimiter


def codes(problems):
    return [problem.code for problem in problems]


class TestCleanInput:
    def test_a_tidy_file_has_no_problems(self):
        assert lint_csv("a,b\n1,2\n3,4\n") == []

    def test_a_header_only_file_is_fine(self):
        assert lint_csv("a,b\n") == []

    def test_quoted_fields_with_commas(self):
        assert lint_csv('a,b\n"x, y",2\n') == []

    def test_a_quoted_field_spanning_lines(self):
        assert lint_csv('a,b\n"line1\nline2",2\n') == []

    def test_crlf_input(self):
        assert lint_csv("a,b\r\n1,2\r\n") == []

    def test_a_trailing_blank_line_is_not_a_row(self):
        assert lint_csv("a,b\n1,2\n\n") == []

    def test_other_delimiters(self):
        assert lint_csv("a;b\n1;2\n", delimiter=";") == []

    def test_tabs(self):
        assert lint_csv("a\tb\n1\t2\n", delimiter="\t") == []


class TestHeader:
    def test_a_bom_is_reported(self):
        problems = lint_csv("\ufeffa,b\n1,2\n")
        assert codes(problems) == ["bom"]

    def test_a_bom_is_stripped_so_columns_still_match(self):
        problems = lint_csv("\ufeffa,b\n1,2\n", expected_header=["a", "b"])
        assert codes(problems) == ["bom"]

    def test_duplicate_columns(self):
        problems = lint_csv("a,b,a\n1,2,3\n")
        assert codes(problems) == ["duplicate-header"]
        assert problems[0].column == 3
        assert "'a' already appears in column 1" in problems[0].message

    def test_duplicates_compare_after_stripping(self):
        assert set(codes(lint_csv("a, a\n1,2\n"))) == {"duplicate-header", "padded-header"}

    def test_an_empty_column_name(self):
        problems = lint_csv("a,,c\n1,2,3\n")
        assert codes(problems) == ["empty-header"]
        assert problems[0].column == 2

    def test_a_padded_column_name(self):
        problems = lint_csv("a , b\n1,2\n")
        assert codes(problems) == ["padded-header", "padded-header"]

    def test_an_empty_header_row(self):
        assert "empty-header" in codes(lint_csv(",,\n1,2,3\n"))

    def test_an_empty_file(self):
        assert codes(lint_csv("")) == ["empty-file"]

    def test_a_nul_byte_is_reported(self):
        problems = lint_csv("a,b\n1,\x002\n")
        assert codes(problems) == ["nul-byte"]
        assert problems[0].line == 2

    def test_undecodable_bytes(self):
        problems = lint_csv(b"a,b\n\xff\xfe\n")
        assert codes(problems) == ["encoding"]


class TestRagged:
    def test_a_short_row(self):
        problems = lint_csv("a,b\n1\n")
        assert codes(problems) == ["ragged-row"]
        assert problems[0].line == 2
        assert "1 field(s), header has 2" in problems[0].message

    def test_a_long_row(self):
        problems = lint_csv("a,b\n1,2,3\n")
        assert codes(problems) == ["ragged-row"]

    def test_every_bad_row_is_reported(self):
        problems = lint_csv("a,b\n1\n2,3\n4\n")
        assert [problem.line for problem in problems] == [2, 4]

    def test_ragged_rows_can_be_allowed(self):
        assert lint_csv("a,b\n1\n", allow_ragged=True) == []

    def test_the_line_number_counts_a_multiline_field(self):
        problems = lint_csv('a,b\n"x\ny",2\n1\n')
        assert [problem.line for problem in problems] == [4]


class TestExpectedHeader:
    def test_a_missing_column(self):
        problems = lint_csv("a,b\n1,2\n", expected_header=["a", "b", "c"])
        assert codes(problems) == ["missing-column"]
        assert "expected column 'c'" in problems[0].message

    def test_an_extra_column(self):
        problems = lint_csv("a,b,c\n1,2,3\n", expected_header=["a", "b"])
        assert codes(problems) == ["extra-column"]
        assert "'c'" in problems[0].message

    def test_a_matching_header(self):
        assert lint_csv("a,b\n1,2\n", expected_header=["a", "b"]) == []

    def test_column_order_does_not_matter(self):
        assert lint_csv("b,a\n1,2\n", expected_header=["a", "b"]) == []

    def test_expected_names_are_stripped(self):
        assert lint_csv("a,b\n1,2\n", expected_header=[" a ", "b"]) == []


class TestOrdering:
    def test_problems_are_sorted_by_line_then_column(self):
        problems = lint_csv("\ufeffa,,a\n1\n", expected_header=["z"])
        assert problems == sorted(problems, key=lambda p: (p.line, p.column or 0))
        assert problems[0].code == "bom"
        assert problems[-1].code == "ragged-row"
        assert len(problems) >= 5

    def test_bad_delimiter_length(self):
        with pytest.raises(ValueError, match="one character"):
            lint_csv("a,b\n", delimiter=",;")


class TestProblem:
    def test_str_with_column(self):
        assert str(Problem(2, 3, "code", "message")) == "line 2, column 3: message (code)"

    def test_str_without_column(self):
        assert str(Problem(2, None, "code", "message")) == "line 2: message (code)"


class TestSniffDelimiter:
    def test_comma(self):
        assert sniff_delimiter("a,b,c\n1,2,3\n") == ","

    def test_semicolon(self):
        assert sniff_delimiter("a;b;c\n1;2;3\n") == ";"

    def test_tab(self):
        assert sniff_delimiter("a\tb\n1\t2\n") == "\t"

    def test_pipe(self):
        assert sniff_delimiter("a|b\n1|2\n") == "|"

    def test_a_single_column_file_keeps_the_first_candidate(self):
        assert sniff_delimiter("a\n1\n") == ","

    def test_accepts_bytes(self):
        assert sniff_delimiter(b"a;b\n1;2\n") == ";"

    def test_undecodable_bytes_raise(self):
        with pytest.raises(ValueError, match="undecodable"):
            sniff_delimiter(b"\xff\xfe\x00")


class TestCommandLine:
    def run(self, argv):
        from columncheck.__main__ import main

        return main(argv)

    def write(self, tmp_path, text, name="data.csv"):
        path = tmp_path / name
        # write_text(newline=...) is 3.10+, and this suite runs on 3.9 too
        path.write_bytes(text.encode("utf-8"))
        return str(path)

    def test_a_clean_file_exits_zero(self, tmp_path, capsys):
        path = self.write(tmp_path, "a,b\n1,2\n")
        assert self.run([path]) == 0
        assert "0 problem(s)" in capsys.readouterr().err

    def test_a_ragged_file_exits_one(self, tmp_path, capsys):
        path = self.write(tmp_path, "a,b\n1\n")
        assert self.run([path]) == 1
        assert "ragged-row" in capsys.readouterr().err

    def test_json_output(self, tmp_path, capsys):
        path = self.write(tmp_path, "a,b\n1\n")
        assert self.run([path, "--json"]) == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload[0]["code"] == "ragged-row"
        assert payload[0]["line"] == 2

    def test_header_option(self, tmp_path, capsys):
        path = self.write(tmp_path, "a,b\n1,2\n")
        assert self.run([path, "--header", "a,b,c"]) == 1
        assert "missing-column" in capsys.readouterr().err

    def test_allow_ragged(self, tmp_path):
        path = self.write(tmp_path, "a,b\n1\n")
        assert self.run([path, "--allow-ragged"]) == 0

    def test_delimiter_option(self, tmp_path):
        path = self.write(tmp_path, "a;b\n1;2\n")
        assert self.run([path, "--delimiter", ";"]) == 0

    def test_sniff_option(self, tmp_path):
        path = self.write(tmp_path, "a;b\n1;2\n")
        assert self.run([path, "--sniff"]) == 0

    def test_missing_file_exits_two(self, tmp_path, capsys):
        assert self.run([str(tmp_path / "nope.csv")]) == 2
        assert "no such file" in capsys.readouterr().err


class TestRigour:
    """csv module errors, blank lines and the CLI's own error path."""

    def test_a_header_that_csv_refuses(self):
        problems = lint_csv("a" * 200_000 + ",b\n1,2\n")
        assert problems[0].code == "malformed"
        assert "cannot read the header" in problems[0].message

    def test_a_data_row_that_csv_refuses(self):
        problems = lint_csv("a,b\n" + "x" * 200_000 + ",2\n")
        assert problems[0].code == "malformed"
        assert problems[0].line == 2

    def test_an_empty_record_is_skipped(self):
        assert lint_csv("a,b\n\n1,2\n") == []

    def test_a_ragged_row_can_be_allowed(self):
        assert lint_csv("a,b\n1,2,3\n", allow_ragged=True) == []

    def test_a_header_with_only_one_column(self):
        problems = lint_csv("a\n1\n2\n")
        assert [problem.code for problem in problems] == []

    def test_the_cli_reports_an_undecodable_file(self, tmp_path, capsys):
        from columncheck.__main__ import main

        path = tmp_path / "bad.csv"
        path.write_bytes(b"\xff\xfe\x00a,b\n")
        assert main([str(path)]) == 1
        assert "not valid utf-8" in capsys.readouterr().out

    def test_the_cli_rejects_a_multi_character_delimiter(self, tmp_path, capsys):
        from columncheck.__main__ import main

        path = tmp_path / "ok.csv"
        path.write_text("a,b\n1,2\n", encoding="utf-8")
        assert main([str(path), "--delimiter", "::"]) == 2
        assert "one character" in capsys.readouterr().err


class TestRigour2:
    """Delimiter sniffing at its edges."""

    def test_a_long_file_stops_sampling_after_fifty_rows(self):
        document = "a;b\n" + "1;2\n" * 60
        assert sniff_delimiter(document.encode("utf-8")) == ";"

    def test_an_empty_document_falls_back_to_a_comma(self):
        assert sniff_delimiter(b"") == ","
