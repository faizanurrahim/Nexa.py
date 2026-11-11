import pytest

from Nexa.nxscript import NXscriptTemplate, TemplateSyntaxError


@pytest.mark.parametrize(
    ("source", "context", "expected"),
    [
        (
            "{%if x %}X{%elif y %}A{%if z %}Z{%else%}NZ{%end if%}B"
            "{%else%}N{%end if%}",
            {"x": False, "y": True, "z": False},
            "ANZB",
        ),
        (
            "{%if x %}X{%else%}A{%if y %}Y{%else%}NY{%end if%}B{%end if%}",
            {"x": False, "y": False},
            "ANYB",
        ),
        (
            "{%if x %}X{%elif y %}A{%if z %}Z{%else%}NZ{%end if%}B"
            "{%elif w %}W{%else%}N{%end if%}",
            {"x": False, "y": True, "z": False, "w": False},
            "ANZB",
        ),
        (
            "{%if a %}{%if b %}{%if c %}C{%else%}NC{%end if%}"
            "{%else%}NB{%end if%}{%else%}NA{%end if%}",
            {"a": True, "b": True, "c": False},
            "NC",
        ),
        (
            "{%if x %}yes{%elif y %}also yes{%else%}no{%end if%}",
            {"x": False, "y": True},
            "also yes",
        ),
    ],
)
def test_if_chain_handles_nested_branches(source, context, expected):
    assert NXscriptTemplate(source).render(**context) == expected


def test_if_chain_requires_matching_end_tag():
    with pytest.raises(TemplateSyntaxError, match="Unclosed if statement"):
        NXscriptTemplate("{%if x %}missing end").render(x=True)


@pytest.mark.parametrize(
    "source",
    [
        "{%if x %}one{%else%}two{%else%}three{%end if%}",
        "{%if x %}one{%else%}two{%elif y %}three{%end if%}",
    ],
)
def test_if_chain_rejects_branches_after_else(source):
    with pytest.raises(
        TemplateSyntaxError,
        match="cannot follow an else branch",
    ):
        NXscriptTemplate(source).render(x=False, y=True)
