import io

import pytest

from Nexa.nxlang import (
    ERROR_TYPES,
    ERR,
    CompileERR,
    EnvironmentERR,
    ImportERR,
    InternalERR,
    ModuleRegistry,
    ModuleERR,
    NameERR,
    NXLang,
    RuntimeERR,
    SyntaxERR,
    TypeERR,
    get_environment,
    list_environments,
)
from Nexa.nxlang.lexer import Lexer


def run(source, **kwargs):
    stream = io.StringIO()
    NXLang(stream=stream, **kwargs).run(source)
    return stream.getvalue()


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------


def test_error_hierarchy_root_and_kinds():
    for name in (
        "SyntaxERR",
        "CompileERR",
        "RuntimeERR",
        "ImportERR",
        "ModuleERR",
        "EnvironmentERR",
        "TypeERR",
        "NameERR",
        "InternalERR",
    ):
        cls = ERROR_TYPES[name]
        assert issubclass(cls, ERR)
        assert cls.kind == name
    assert ERR.kind == "ERR"


def test_error_carries_source_location():
    error = SyntaxERR("bad token", filename="main.nx", line=4, column=9)
    assert error.location == "main.nx:4:9"
    assert str(error) == "main.nx:4:9: bad token"
    assert error.format() == "SyntaxERR: main.nx:4:9: bad token"


# ---------------------------------------------------------------------------
# Execution basics
# ---------------------------------------------------------------------------


def test_print_writes_to_the_runtime_stream():
    assert run('print("hello")') == "hello\n"


def test_arguments_are_available_to_the_program():
    stream = io.StringIO()
    NXLang(stream=stream).run("print(args)", args=["one", "two"])
    assert stream.getvalue() == "['one', 'two']\n"


def test_comments_are_ignored():
    source = "// line comment\n# hash comment\nprint(\"ok\")  // trailing\n"
    assert run(source) == "ok\n"


def test_lexer_rejects_unknown_characters():
    with pytest.raises(SyntaxERR) as excinfo:
        Lexer("@", "bad.nx").tokenize()
    assert excinfo.value.filename == "bad.nx"


# ---------------------------------------------------------------------------
# throw / do / unless
# ---------------------------------------------------------------------------


def test_throw_is_handled_by_matching_do_block():
    source = """
do {
    throw(ERR("boom"))
}
unless ERR as e {
    print("handled")
}
"""
    assert run(source) == "handled\n"


def test_handler_receives_the_error_object():
    source = """
do {
    throw(ERR("boom"))
}
unless ERR as e {
    print(e)
}
"""
    assert "boom" in run(source)


def test_handlers_match_inherited_error_types():
    source = """
do {
    throw(SyntaxERR("bad syntax"))
}
unless ERR as e {
    print("caught by ERR")
}
"""
    assert run(source) == "caught by ERR\n"


def test_handler_can_match_a_concrete_error_type():
    source = """
do {
    throw(SyntaxERR("bad syntax"))
}
unless SyntaxERR as e {
    print("caught by SyntaxERR")
}
"""
    assert run(source) == "caught by SyntaxERR\n"


def test_first_matching_handler_wins():
    source = """
do {
    throw(SyntaxERR("bad syntax"))
}
unless CompileERR as e {
    print("wrong handler")
}
unless ERR as e {
    print("second handler")
}
"""
    assert run(source) == "second handler\n"


def test_unmatched_error_propagates_to_the_runtime():
    source = """
do {
    throw(SyntaxERR("bad syntax"))
}
unless CompileERR as e {
    print("wrong handler")
}
"""
    with pytest.raises(SyntaxERR):
        run(source)


def test_unhandled_error_propagates():
    with pytest.raises(ERR):
        run('throw(ERR("unhandled"))')


def test_throw_requires_an_error_object():
    with pytest.raises(TypeERR):
        run('throw("plain string")')


def test_unknown_handler_error_type_is_reported():
    source = """
do {
    throw(ERR("boom"))
}
unless NoSuchERR as e {
    print("never")
}
"""
    with pytest.raises(NameERR):
        run(source)


def test_syntax_error_reports_a_position():
    with pytest.raises(SyntaxERR) as excinfo:
        run("do {\n")
    assert excinfo.value.line == 2 or excinfo.value.line == 3
    assert excinfo.value.filename == "<nx>"


# ---------------------------------------------------------------------------
# Module inclusion
# ---------------------------------------------------------------------------


def test_regular_and_internal_modules_resolve():
    source = """
include <base_compiler> as bc
include <<_request_handler>> as rh
print("ok")
"""
    assert run(source) == "ok\n"


def test_missing_regular_module_raises_import_error():
    with pytest.raises(ImportERR, match="base_compiler_absent"):
        run("include <base_compiler_absent> as missing\n")


def test_missing_internal_module_raises_module_error():
    with pytest.raises(ModuleERR, match="_not_registered_"):
        run("include <<_not_registered_>> as missing\n")


def test_internal_modules_are_not_python_imports():
    with pytest.raises(ModuleERR):
        run("include <<os>> as target\n")


def test_custom_module_registry_is_used():
    registry = ModuleRegistry()
    registry.register("custom", exports={"kind": "custom"})
    stream = io.StringIO()
    NXLang(modules=registry, stream=stream).run('include <custom> as c\nprint("ok")')
    assert stream.getvalue() == "ok\n"


# ---------------------------------------------------------------------------
# Environments, files and compilation
# ---------------------------------------------------------------------------


def test_native_environment_is_the_default():
    assert get_environment().name == "nx"
    assert "nx" in list_environments()
    assert "py" in list_environments()


def test_python_environment_is_not_implemented_yet():
    with pytest.raises(EnvironmentERR):
        NXLang(environment="py").run("")


def test_unknown_environment_is_rejected():
    with pytest.raises(EnvironmentERR):
        NXLang(environment="rust")


def test_compile_returns_a_program_without_executing():
    compiled = NXLang().compile('print("never run")', filename="demo.nx")
    assert compiled.filename == "demo.nx"
    assert compiled.program.body


def test_run_file_executes_source(tmp_path):
    script = tmp_path / "main.nx"
    script.write_text('print("from-file")\n', encoding="utf-8")
    stream = io.StringIO()
    NXLang(stream=stream).run_file(script)
    assert stream.getvalue() == "from-file\n"


def test_run_file_rejects_non_nx_files(tmp_path):
    script = tmp_path / "main.txt"
    script.write_text("print('nope')\n", encoding="utf-8")
    with pytest.raises(ImportERR):
        NXLang().run_file(script)


def test_run_file_reports_missing_files(tmp_path):
    with pytest.raises(ImportERR):
        NXLang().run_file(tmp_path / "absent.nx")


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


def test_cli_exec_runs_nxlang_file(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from Nexa.nexa import app as cli

    (tmp_path / "main.nx").write_text('print("from-cli")\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["exec", "main"])

    assert result.exit_code == 0, result.output
    assert "from-cli" in result.output


def test_cli_exec_passes_arguments(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from Nexa.nexa import app as cli

    (tmp_path / "args.nx").write_text("print(args)\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["exec", "args", "one", "two"])

    assert result.exit_code == 0, result.output
    assert "['one', 'two']" in result.output


def test_cli_exec_reports_missing_source(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from Nexa.nexa import app as cli

    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["exec", "missing.nx"])
    output = result.output + getattr(result, "stderr", "")

    assert result.exit_code == 1
    assert "not found" in output


def test_cli_exec_reports_nxlang_errors(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from Nexa.nexa import app as cli

    (tmp_path / "broken.nx").write_text('throw(ERR("nope"))\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["exec", "broken"])
    output = result.output + getattr(result, "stderr", "")

    assert result.exit_code == 1
    assert "nope" in output
