
import re
from pathlib import Path


class NexaSyntaxError(Exception):
    pass


TAG_OPEN = re.compile(
    r"^\s*<([A-Za-z][\w.-]*)(.*?)>\s*$"
)

TAG_INLINE = re.compile(
    r"^\s*<([A-Za-z][\w.-]*)(.*?)>(.*?)</\1>\s*$"
)

FOR_LINE = re.compile(r"^for\s+(.+?)\s*:\s*$")

ATTRIBUTE = re.compile(
    r"""([:\w-]+)\s*=\s*("([^"]*)"|'([^']*)'|\{([^{}]*)\})"""
)


def indentation(line):
    return len(line) - len(line.lstrip())


def compile_text(text):
    """Convert text with {expressions} into a Python expression."""
    parts = []
    position = 0

    for match in re.finditer(r"\{([^{}]+)\}", text):
        literal = text[position:match.start()]
        expression = match.group(1).strip()

        if literal:
            parts.append(repr(literal))

        if not expression:
            raise NexaSyntaxError("Empty expression inside {}")

        parts.append(f"str({expression})")
        position = match.end()

    remaining = text[position:]

    if remaining:
        parts.append(repr(remaining))

    if not parts:
        return "''"

    return " + ".join(parts)


def compile_attributes(source):
    props = {}

    for match in ATTRIBUTE.finditer(source):
        name = match.group(1)

        if match.group(5) is not None:
            value = match.group(5).strip()
            if not value:
                raise NexaSyntaxError(
                    f"Empty expression for attribute {name!r}"
                )
        else:
            value = repr(
                match.group(3)
                if match.group(3) is not None
                else match.group(4)
            )

        props[name] = value

    # Reject attribute syntax this prototype doesn't understand.
    residue = ATTRIBUTE.sub("", source).strip()
    if residue:
        raise NexaSyntaxError(
            f"Unsupported attribute syntax: {residue}"
        )

    return "{" + ", ".join(
        f"{name!r}: {value}"
        for name, value in props.items()
    ) + "}"


def parse_node(lines, index):
    """Parse one JSX-like element or a loop containing one element."""
    while index < len(lines) and not lines[index].strip():
        index += 1

    if index >= len(lines):
        raise NexaSyntaxError("Expected an element")

    line = lines[index]
    indent = indentation(line)
    stripped = line.strip()

    loop_match = FOR_LINE.fullmatch(stripped)

    if loop_match:
        target = loop_match.group(1)

        body_index = index + 1
        while body_index < len(lines) and not lines[body_index].strip():
            body_index += 1

        if body_index >= len(lines):
            raise NexaSyntaxError("Loop has no body")

        if indentation(lines[body_index]) <= indent:
            raise NexaSyntaxError(
                f"Loop body must be indented: {stripped}"
            )

        body_expr, next_index = parse_node(lines, body_index)

        return (
            f"*({body_expr} for {target})",
            next_index,
        )

    inline = TAG_INLINE.fullmatch(line)

    if inline:
        tag = inline.group(1)
        raw_attrs = opening.group(2).strip()

        # Remove the trailing slash from self-closing tags.
        if raw_attrs.endswith("/"):
            raw_attrs = raw_attrs[:-1].rstrip()

        attrs = compile_attributes(raw_attrs)
        content = compile_text(inline.group(3))

        return f"Element({tag!r}, {attrs}, {content})", index + 1

    opening = TAG_OPEN.fullmatch(line)

    if not opening:
        raise NexaSyntaxError(
            f"Expected a JSX element at line {index + 1}: {stripped}"
        )

    tag = opening.group(1)
    attrs = compile_attributes(opening.group(2))
    children = []
    index += 1

    while index < len(lines):
        current = lines[index]
        current_text = current.strip()

        if not current_text:
            index += 1
            continue

        if current_text == f"</{tag}>":
            index += 1
            break

        if current_text.startswith("</"):
            raise NexaSyntaxError(
                f"Unexpected closing tag at line {index + 1}: "
                f"{current_text}"
            )

        if indentation(current) <= indent:
            raise NexaSyntaxError(
                f"Missing closing tag </{tag}>"
            )

        child_expr, index = parse_node(lines, index)
        children.append(child_expr)

    else:
        raise NexaSyntaxError(f"Missing closing tag </{tag}>")

    return (
        f"Element({tag!r}, {attrs}"
        + (", " + ", ".join(children) if children else "")
        + ")",
        index,
    )


def compile_source(source):
    """Translate supported .nx markup into Python source."""
    lines = source.splitlines()
    output = []
    index = 0

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if stripped.startswith("<") and not stripped.startswith("</"):
            indent = indentation(line)
            expression, next_index = parse_node(lines, index)

            output.append(" " * indent + expression)
            index = next_index
        else:
            output.append(line)
            index += 1

    return "\n".join(output) + "\n"


def compile_file(path):
    path = Path(path)
    return compile_source(path.read_text(encoding="utf-8"))
