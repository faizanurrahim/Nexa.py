"""
NXscript — Nexa's native template and scripting language.

Supports:
- Template variables: {{ variable }}
- Loops: {%for item in items %}...{%end for%}
- Conditionals: {%if condition %}...{%elif other %}...{%else%}...{%end if%}
- Template inheritance: {%extends "base.html" %}{%block name %}...{%end block %}
- Variable declarations with browser sync: {@varname Type} ... {end var}
"""

from __future__ import annotations

import re
from html import escape
from pathlib import Path
from typing import Any, Optional

from .template import (
    TemplateError,
    TemplateSyntaxError,
    TemplateRenderError,
    TemplateNotFound,
    _TEMPLATE_VARIABLE,
)


# ---------------------------------------------------------------------------
# Safe expression evaluator
# ---------------------------------------------------------------------------

# Allowed builtins for template expressions — no exec, eval, open, etc.
_SAFE_BUILTINS = {
    "str": str,
    "len": len,
    "range": range,
    "list": list,
    "dict": dict,
    "tuple": tuple,
    "set": set,
    "enumerate": enumerate,
    "zip": zip,
    "min": min,
    "max": max,
    "sum": sum,
    "abs": abs,
    "round": round,
    "bool": bool,
    "int": int,
    "float": float,
    "True": True,
    "False": False,
    "None": None,
    "isinstance": isinstance,
    "type": type,
    "format": format,
    "chr": chr,
    "ord": ord,
    "hex": hex,
    "oct": oct,
    "bin": bin,
    "repr": repr,
    "sorted": sorted,
    "reversed": reversed,
    "any": any,
    "all": all,
    "pow": pow,
    "divmod": divmod,
}


class SafeEvaluator:
    """Evaluate template expressions safely without exposing dangerous builtins."""

    def __init__(self, context: dict[str, Any]) -> None:
        self._namespace: dict[str, Any] = {
            "__builtins__": _SAFE_BUILTINS,
        }
        self._namespace.update(context)

    def evaluate(self, expression: str) -> Any:
        """Evaluate *expression* in the safe namespace."""
        expression = expression.strip()
        if not expression:
            raise TemplateSyntaxError("Empty expression")

        try:
            return eval(expression, self._namespace)
        except NameError as exc:
            name = exc.name if exc.name else "unknown"
            raise TemplateRenderError(
                f"Unknown variable '{name}' in expression '{expression}'"
            ) from exc
        except AttributeError as exc:
            # Try to handle attribute access on dicts (e.g., user.admin -> user['admin'])
            if '.' in expression:
                parts = expression.split('.', 1)
                try:
                    obj = eval(parts[0], self._namespace)
                    if isinstance(obj, dict):
                        return obj[parts[1]]
                except (KeyError, IndexError, Exception):
                    pass
            raise TemplateRenderError(
                f"Error evaluating '{expression}': {exc}"
            ) from exc
        except Exception as exc:
            raise TemplateRenderError(
                f"Error evaluating '{expression}': {exc}"
            ) from exc


# ---------------------------------------------------------------------------
# Token types
# ---------------------------------------------------------------------------

# Match {% ... %} tags
_BLOCK_TAG = re.compile(r"\{\%\s*(.*?)\s*\%\}")

# Match {@ ... } variable declarations
_VAR_DECL = re.compile(r"\{\@\s*(\w+)\s+(\w+)(.*?)\}\s*$")

# Match {{ ... }} variable expressions
_VAR_EXPR = re.compile(r"\{\{\s*(.+?)\s*\}\}")

# Inheritance
_EXTENDS = re.compile(r"\{\%\s*extends\s+[\"'](.+?)[\"']\s*\%\}")
_BLOCK_DEF = re.compile(
    r"\{%\s*block\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*%\}"
)

_BLOCK_END = re.compile(
    r"\{%\s*endblock(?:\s+[a-zA-Z_][a-zA-Z0-9_]*)?\s*%\}"
)
# Loops
_FOR = re.compile(r"\{\%\s*for\s+(\w+)\s+in\s+(.+?)\s*\%\}")
_FOR_END = re.compile(r"\{\%\s*end\s+for\s*\%\}")

# Conditionals
_IF = re.compile(r"\{\%\s*if\s+(.+?)\s*\%\}")
_ELIF = re.compile(r"\{\%\s*elif\s+(.+?)\s*\%\}")
_ELSE = re.compile(r"\{\%\s*else\s*\%\}")
_IF_END = re.compile(r"\{\%\s*end\s+if\s*\%\}")


# ---------------------------------------------------------------------------
# Block nodes
# ---------------------------------------------------------------------------

class BlockNode:
    """A named block in a template (for inheritance)."""

    def __init__(self, name: str, content: str = "", children: list = None):
        self.name = name
        self.content = content
        self.children = children or []

    def render(self, context: dict[str, Any], blocks: dict[str, "BlockNode"]) -> str:
        """Render this block. Child templates can override."""
        return self.content


class ForNode:
    """A for loop node."""

    def __init__(self, variable: str, iterable_expr: str, body: str, render_fn=None):
        self.variable = variable
        self.iterable_expr = iterable_expr
        self.body = body
        self._render_fn = render_fn  # Function to render nested content

    def render(self, evaluator: SafeEvaluator) -> str:
        iterable = evaluator.evaluate(self.iterable_expr)
        try:
            items = list(iterable)
        except TypeError as exc:
            raise TemplateRenderError(
                f"Cannot iterate over {self.iterable_expr!r}: {exc}"
            ) from exc

        results = []
        original_namespace = dict(evaluator._namespace)
        
        for idx, item in enumerate(items):
            # Create a new namespace for this iteration
            ctx = dict(original_namespace)
            ctx[self.variable] = item
            # Also provide loop info
            ctx["loop_index"] = idx
            ctx["loop_first"] = idx == 0
            ctx["loop_last"] = idx == len(items) - 1
            ctx["loop_length"] = len(items)

            # Create a new evaluator with the updated namespace
            iter_evaluator = SafeEvaluator.__new__(SafeEvaluator)
            iter_evaluator._namespace = ctx
            
            try:
                if self._render_fn:
                    # Use the provided render function for nested content
                    results.append(self._render_fn(self.body, iter_evaluator))
                else:
                    # Fall back to simple string rendering
                    results.append(_render_string(self.body, iter_evaluator))
            finally:
                pass

        return "".join(results)


class IfNode:
    """A conditional node with if/elif/else branches."""

    def __init__(self, branches: list, render_fn=None):
        """
        branches: list of (condition_expr_or_None, body_str)
        - condition_expr_or_None is None for the else branch
        - body_str is the raw template text for that branch
        """
        self.branches = branches
        self._render_fn = render_fn  # Function to render nested content

    def render(self, evaluator: SafeEvaluator) -> str:
        for condition, body in self.branches:
            if condition is None:
                # else branch — always render
                if self._render_fn:
                    return self._render_fn(body, evaluator)
                return _render_string(body, evaluator)
            try:
                result = evaluator.evaluate(condition)
            except Exception:
                # If evaluation fails, treat as falsy
                continue
            if result:
                if self._render_fn:
                    return self._render_fn(body, evaluator)
                return _render_string(body, evaluator)
        return ""


class ExtendsNode:
    """Marker that this template extends another."""

    def __init__(self, parent_name: str):
        self.parent_name = parent_name


class VariableDeclaration:
    """A {@varname Type} declaration for browser sync."""

    def __init__(self, name: str, type_name: str, body: str):
        self.name = name
        self.type_name = type_name
        self.body = body


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class NXscriptParser:
    """Parse NXscript source into a structured representation."""

    def __init__(self, source: str, filename: str = "<template>"):
        self.source = source
        self.filename = filename
        self.position = 0
        self.blocks: dict[str, str] = {}  # name -> body content
        self.parent_template: Optional[str] = None
        self.variable_decls: list[VariableDeclaration] = []
        self._parsed_blocks: dict[str, BlockNode] = {}

    def parse(self) -> dict:
        """
        Parse the template and return a structure with:
        - parent: parent template name or None
        - blocks: dict of block_name -> BlockNode
        - content: the main template content (or None if only extends)
        - variable_decls: list of variable declarations
        """
        # First pass: find extends, blocks, and variable declarations
        self._extract_metadata()

        # Build the parsed structure
        return {
            "parent": self.parent_template,
            "blocks": self._parsed_blocks,
            "content": self._get_content(),
            "variable_decls": self.variable_decls,
        }

    def _extract_metadata(self):
        """Extract extends, blocks, and variable declarations from source."""
        # Find extends
        match = _EXTENDS.search(self.source)
        if match:
            self.parent_template = match.group(1)

        # Find all block definitions and their content
        self._extract_blocks()

        # Find variable declarations
        self._extract_variable_decls()

    def _extract_blocks(self):
        """Extract {% block name %}...{% end block %} definitions."""
        pos = 0
        while pos < len(self.source):
            # Look for block start
            block_match = _BLOCK_DEF.search(self.source, pos)
            if not block_match:
                break

            block_name = block_match.group(1)
            block_start = block_match.end()
            block_end_match = _BLOCK_END.search(self.source, block_start)

            if not block_end_match:
                raise TemplateSyntaxError(
                    f"Unclosed block '{block_name}' in {self.filename}"
                )

            block_content = self.source[block_start:block_end_match.start()]
            self.blocks[block_name] = block_content
            self._parsed_blocks[block_name] = BlockNode(block_name, block_content)
            pos = block_end_match.end()

    def _extract_variable_decls(self):
        """Extract {@varname Type} declarations."""
        for match in _VAR_DECL.finditer(self.source):
            name = match.group(1)
            type_name = match.group(2)
            # Get body until {end var}
            body_start = match.end()
            end_match = re.search(
                r"\{%\s*end\s+var\s*\%\}",
                self.source[body_start:]
            )
            if end_match:
                body = self.source[body_start:body_start + end_match.start()]
            else:
                body = ""
            self.variable_decls.append(
                VariableDeclaration(name, type_name, body)
            )

    def _get_content(self) -> str:
        """Get the main template content, excluding block definitions."""
        if self.parent_template:
            # For child templates, return the blocks that override parent
            return self.blocks
        return self.source


# ---------------------------------------------------------------------------
# Template class
# ---------------------------------------------------------------------------

class NXscriptTemplate:
    """
    A compiled NXscript template.

    Supports inheritance: a child template can extend a parent and override
    named blocks.
    """

    def __init__(self, source: str, filename: str = "<template>"):
        self._filename = filename
        self._source = source
        self._parser = NXscriptParser(source, filename)
        self._structure = self._parser.parse()
        self._parent_template: Optional[NXscriptTemplate] = None
        self._is_child = self._structure["parent"] is not None

    def set_parent(self, parent: "NXscriptTemplate") -> None:
        """Set the parent template for inheritance."""
        self._parent_template = parent

    def render(self, **context: Any) -> str:
        """Render the template with the given context variables."""
        evaluator = SafeEvaluator(context)

        if self._is_child and self._parent_template:
            # Child template: render parent with overridden blocks
            return self._render_child(evaluator)
        else:
            # Standalone template or parent - need to process all block tags
            return self._render_source(self._source, evaluator)

    def _render_child(self, evaluator: SafeEvaluator) -> str:
        """Render a child template by combining with parent."""
        # Override blocks in the parent
        parent_blocks = self._parent_template._structure.get("blocks", {})
        blocks = {}
        for name, content in parent_blocks.items():
            # Store the raw content string, not BlockNode objects
            if hasattr(content, 'content'):
                blocks[name] = content.content
            else:
                blocks[name] = content
        
        # Update with child's blocks (override parent blocks)
        for name, node in self._structure["blocks"].items():
            if hasattr(node, 'content'):
                blocks[name] = node.content
            else:
                blocks[name] = str(node)

        # Render parent with overridden blocks
        parent_source = self._parent_template._source
        return self._render_with_blocks(parent_source, evaluator, blocks)

    def _render_with_blocks(
        self, source: str, evaluator: SafeEvaluator, blocks: dict
    ) -> str:
        """Render source with block overrides."""
        return self._render_nodes(source, evaluator, blocks)

    def _render_with_blocks(
        self, source: str, evaluator: SafeEvaluator, blocks: dict
    ) -> str:
        """Render source with block overrides."""
        # Create a render function that captures blocks
        def render_fn(source: str, evaluator: SafeEvaluator) -> str:
            return self._render_nodes(source, evaluator, blocks)
        
        return render_fn(source, evaluator)

    def _render_nodes(self, source: str, evaluator: SafeEvaluator, blocks: dict) -> str:
        """Recursively render template nodes, handling all block types."""
        result = []
        pos = 0

        while pos < len(source):
            # Find the next significant tag
            next_tag = None
            tag_type = None
            
            for tag_name, pattern in [("block", _BLOCK_DEF), ("endblock", _BLOCK_END), 
                                       ("for", _FOR), ("endfor", _FOR_END),
                                       ("if", _IF), ("endif", _IF_END),
                                       ("elif", _ELIF), ("else", _ELSE)]:
                m = pattern.search(source, pos)
                if m and (next_tag is None or m.start() < next_tag.start()):
                    next_tag = m
                    tag_type = tag_name

            if next_tag is None:
                # No more tags, render remaining text
                result.append(_render_string(source[pos:], evaluator))
                break

            # Render text before the tag
            if next_tag.start() > pos:
                result.append(_render_string(source[pos:next_tag.start()], evaluator))

            tag_text = next_tag.group(0)

            # Process based on tag type
            if tag_type == "block":
                block_name = next_tag.group(1)
                block_end = _BLOCK_END.search(source, next_tag.end())
                if block_end:
                    overridden = blocks.get(block_name, "")
                    if overridden:
                        # Recursively render the overridden block content
                        if isinstance(overridden, str):
                            result.append(self._render_nodes(overridden, evaluator, blocks))
                        else:
                            # It's already a BlockNode or other object, convert to string
                            result.append(str(overridden))
                    pos = block_end.end()
                else:
                    pos = next_tag.end()

            elif tag_type == "endblock":
                pos = next_tag.end()

            elif tag_type == "for":
                # Parse for loop with proper nested handling
                var_match = re.match(r"\{\%\s*for\s+(\w+)\s+in\s+(.+?)\s*\%\}", tag_text)
                if var_match:
                    var_name = var_match.group(1)
                    iterable_expr = var_match.group(2)
                    # Find the matching end for tag (handles nesting)
                    end_for = self._find_matching_end_tag(source, next_tag.end(), _FOR, _FOR_END)
                    if not end_for:
                        raise TemplateSyntaxError("Unclosed for loop")
                    loop_body = source[next_tag.end():end_for.start()]
                    # Pass the render function for nested content
                    for_node = ForNode(var_name, iterable_expr, loop_body, 
                                       render_fn=lambda s, e: self._render_nodes(s, e, blocks))
                    result.append(for_node.render(evaluator))
                    pos = end_for.end()
                else:
                    pos = next_tag.end()

            elif tag_type == "endfor":
                pos = next_tag.end()

            elif tag_type == "if":
                # We already found the if tag via regex, so pass the condition
                if_match = _IF.match(tag_text)
                if if_match:
                    condition = if_match.group(1)
                    # Parse the chain starting from after the if tag
                    if_node = self._parse_if_chain(source, next_tag.end(), initial_condition=condition)
                    # Pass the render function for nested content
                    if_node._render_fn = lambda s, e: self._render_nodes(s, e, blocks)
                    result.append(if_node.render(evaluator))
                    pos = if_node._end_pos
                else:
                    pos = next_tag.end()

            elif tag_type == "endif":
                pos = next_tag.end()

            elif tag_type in ("elif", "else"):
                # These should be handled within _parse_if_chain, skip them
                pos = next_tag.end()

            else:
                # Unknown tag, escape and render as text
                result.append(escape(tag_text))
                pos = next_tag.end()

        return "".join(result)

    def _parse_if_chain(
        self,
        source: str,
        start_pos: int,
        initial_condition: Optional[str] = None,
    ) -> IfNode:
        """Parse an if/elif/else chain, handling nested if statements.
        """

        if initial_condition is not None:
            condition = initial_condition
            body_start = start_pos
        else:
            if_match = _IF.search(source, start_pos)
            if not if_match:
                raise TemplateSyntaxError("Expected if tag")
            condition = if_match.group(1)
            body_start = if_match.end()
            start_pos = body_start

        tag_patterns = (
            ("if", _IF),
            ("elif", _ELIF),
            ("else", _ELSE),
            ("endif", _IF_END),
        )
        tags = sorted(
            (
                (match.start(), tag_type, match)
                for tag_type, pattern in tag_patterns
                for match in pattern.finditer(source, start_pos)
            ),
            key=lambda item: item[0],
        )

        branches: list[tuple[Optional[str], str]] = []
        current_condition: Optional[str] = condition
        current_body_start = body_start
        depth = 1
        else_seen = False

        for _, tag_type, tag_match in tags:
            if tag_type == "if":
                depth += 1
            elif tag_type == "endif":
                depth -= 1
                if depth == 0:
                    branches.append(
                        (current_condition, source[current_body_start:tag_match.start()])
                    )
                    if_node = IfNode(branches)
                    if_node._end_pos = tag_match.end()
                    return if_node
            elif depth == 1 and tag_type in {"elif", "else"}:
                if else_seen:
                    raise TemplateSyntaxError(
                        "An elif or else branch cannot follow an else branch"
                    )

                branches.append(
                    (current_condition, source[current_body_start:tag_match.start()])
                )
                if tag_type == "elif":
                    current_condition = tag_match.group(1)
                else:
                    current_condition = None
                    else_seen = True
                current_body_start = tag_match.end()

        raise TemplateSyntaxError("Unclosed if statement")

    def _find_matching_end_tag(self, source: str, start: int, 
                                   start_pattern: re.Pattern, end_pattern: re.Pattern) -> Optional[re.Match]:
        """Find the matching end tag for a start tag, handling nesting.
        
        Args:
            source: The source string to search
            start: Position to start searching from
            start_pattern: The regex pattern for start tags (e.g., for loops)
            end_pattern: The regex pattern for end tags (e.g., end for)
            
        Returns:
            The match object for the matching end tag, or None if not found.
        """
        depth = 1
        pos = start
        
        while pos < len(source):
            # Find the next start or end tag
            next_start = start_pattern.search(source, pos)
            next_end = end_pattern.search(source, pos)
            
            # If no end tag exists at all, we can't match
            if next_end is None:
                return None
            
            # Determine which tag comes first
            if next_start and next_start.start() < next_end.start():
                # Found a nested start tag, increment depth
                depth += 1
                pos = next_start.end()
            else:
                # Found an end tag
                depth -= 1
                if depth == 0:
                    return next_end
                pos = next_end.end()
        
        # Reached end of source without finding matching end tag
        return None

    def _render_source(self, source: str, evaluator: SafeEvaluator) -> str:
        """Render template source, processing all block tags."""
        return self._render_with_blocks(source, evaluator, {})


# ---------------------------------------------------------------------------
# Public render function
# ---------------------------------------------------------------------------

def _render_string(source: str, evaluator: SafeEvaluator) -> str:
    """Render a string with {{ }} variable interpolation."""
    result = []
    pos = 0

    # Check for empty template expressions like {{}}
    empty_expr = re.compile(r"\{\{\s*\}\}")
    if empty_expr.search(source):
        raise TemplateSyntaxError("Empty template expression")

    for match in _VAR_EXPR.finditer(source):
        # Literal text before the variable
        if match.start() > pos:
            result.append(source[pos:match.start()])

        # Evaluate the expression
        expr = match.group(1).strip()
        if not expr:
            raise TemplateSyntaxError("Empty variable expression")

        try:
            value = evaluator.evaluate(expr)
            result.append(_format_value(value))
        except TemplateRenderError:
            raise
        except Exception as exc:
            raise TemplateRenderError(
                f"Error evaluating '{expr}': {exc}"
            ) from exc

        pos = match.end()

    # Remaining text after last variable
    if pos < len(source):
        result.append(source[pos:])

    return "".join(result)


def _format_value(value: Any) -> str:
    """Format a value for template output.

    Handles special objects like Nforms.Form instances.
    """
    if value is None:
        return ""
    
    # Handle Nforms Form instances with special methods
    if hasattr(value, "as_p"):
        try:
            return value.as_p()
        except Exception:
            pass
    if hasattr(value, "as_table"):
        try:
            return value.as_table()
        except Exception:
            pass
    if hasattr(value, "as_ul"):
        try:
            return value.as_ul()
        except Exception:
            pass
    if hasattr(value, "hidden_tag"):
        try:
            return value.hidden_tag()
        except Exception:
            pass
    
    # Handle form fields
    if hasattr(value, "render"):
        try:
            return value.render()
        except Exception:
            pass
    if hasattr(value, "label"):
        try:
            return _format_label(value)
        except Exception:
            pass
    
    # Handle form errors
    if hasattr(value, "errors"):
        try:
            errors = value.errors
            if isinstance(errors, dict):
                return _format_form_errors(errors)
        except Exception:
            pass
    
    return str(value)


def _format_label(field) -> str:
    """Format a form field's label."""
    label_text = getattr(field, "label", "")
    if not label_text:
        return ""
    field_name = getattr(field, "field_name", "")
    if not field_name:
        # Try to get name from widget
        widget = getattr(field, "widget", None)
        if widget and hasattr(widget, "attrs"):
            field_name = widget.attrs.get("name", "")
    if field_name:
        return f'<label for="{escape_html(field_name)}">{escape_html(label_text)}</label>'
    return escape_html(label_text)


def _format_form_errors(errors: dict) -> str:
    """Format form errors as HTML."""
    if not errors:
        return ""
    html = ['<div class="form-errors">']
    for field_name, field_errors in errors.items():
        for error in field_errors:
            html.append(f'<p class="error">{escape_html(error)}</p>')
    html.append('</div>')
    return "".join(html)


# ---------------------------------------------------------------------------
# Template loader for NXscript
# ---------------------------------------------------------------------------

def _nxscript_loader(app: Any) -> callable:
    """Return an NXscript template loader bound to *app*."""

    def load(template_name: str, **context: Any) -> str:
        path = (app.template_dir / template_name).resolve()
        try:
            relative = path.relative_to(app.template_dir)
        except ValueError:
            raise TemplateNotFound(
                f"Template {template_name!r} resolves outside the template folder "
                f"({app.template_folder!r})."
            ) from None
        if not path.is_file():
            raise TemplateNotFound(
                f"Template {template_name!r} not found in {app.template_folder!r}."
            )

        source = path.read_text(encoding="utf-8")
        template = NXscriptTemplate(source, filename=template_name)

        # Handle inheritance
        if template._structure["parent"]:
            parent_name = template._structure["parent"]
            parent_path = (app.template_dir / parent_name).resolve()
            try:
                relative = parent_path.relative_to(app.template_dir)
            except ValueError:
                raise TemplateNotFound(
                    f"Parent template {parent_name!r} resolves outside the template folder."
                ) from None
            if not parent_path.is_file():
                raise TemplateNotFound(
                    f"Parent template {parent_name!r} not found in {app.template_folder!r}."
                )
            parent_source = parent_path.read_text(encoding="utf-8")
            parent_template = NXscriptTemplate(parent_source, filename=parent_name)
            template.set_parent(parent_template)

        return template.render(**context)

    return load


# ---------------------------------------------------------------------------
# Session state management for browser sync
# ---------------------------------------------------------------------------

class SessionState:
    """
    Manage session-scoped variables for NXscript browser synchronization.

    Each session has its own isolated state. Variables declared with
    {@varname Type} are stored here and can be updated from the browser.
    """

    def __init__(self, session_id: str):
        self._session_id = session_id
        self._variables: dict[str, Any] = {}
        self._types: dict[str, str] = {}  # name -> type name

    def set(self, name: str, value: Any, type_name: str = "str") -> None:
        """Set a variable value."""
        # Type validation
        if type_name == "int":
            try:
                value = int(value)
            except (ValueError, TypeError):
                raise ValueError(f"Variable '{name}' expects an integer")
        elif type_name == "float":
            try:
                value = float(value)
            except (ValueError, TypeError):
                raise ValueError(f"Variable '{name}' expects a float")
        elif type_name == "bool":
            if isinstance(value, str):
                value = value.lower() in ("true", "1", "yes")
            else:
                value = bool(value)
        elif type_name == "list":
            if not isinstance(value, (list, tuple)):
                raise ValueError(f"Variable '{name}' expects a list")

        self._variables[name] = value
        self._types[name] = type_name

    def get(self, name: str, default: Any = None) -> Any:
        """Get a variable value."""
        return self._variables.get(name, default)

    def get_type(self, name: str) -> Optional[str]:
        """Get the declared type of a variable."""
        return self._types.get(name)

    def to_dict(self) -> dict[str, Any]:
        """Export all variables as a dict."""
        return dict(self._variables)

    def from_dict(self, data: dict[str, Any]) -> None:
        """Update variables from a dict (browser updates)."""
        for name, value in data.items():
            if name in self._types:
                self.set(name, value, self._types[name])
            else:
                self._variables[name] = value


# ---------------------------------------------------------------------------
# Global session state registry
# ---------------------------------------------------------------------------

_session_states: dict[str, SessionState] = {}
_session_counter = 0


def get_session_state(session_id: str = None) -> SessionState:
    """Get or create a session state object."""
    global _session_counter
    if session_id is None:
        _session_counter += 1
        session_id = f"session_{_session_counter}"
    if session_id not in _session_states:
        _session_states[session_id] = SessionState(session_id)
    return _session_states[session_id]


def clear_session(session_id: str) -> None:
    """Clear a session's state."""
    if session_id in _session_states:
        del _session_states[session_id]


def get_all_sessions() -> dict[str, SessionState]:
    """Return all active sessions (for debugging)."""
    return dict(_session_states)


# ---------------------------------------------------------------------------
# NXscript renderer with browser sync support
# ---------------------------------------------------------------------------

def render_nxscript(
    template_name: str,
    session_id: str = None,
    **context: Any
) -> str:
    """
    Render an NXscript template with session support.

    Args:
        template_name: The template file name.
        session_id: Optional session ID for browser sync variables.
        **context: Template variables.

    Returns:
        Rendered HTML string.
    """
    from .nxserver import _current_server, _current_request

    server = _current_server.get()
    if server is None:
        raise RuntimeError(
            "render_nxscript(): no active server context. "
            "It can only be called inside a route handler of an NXserver "
            "instance that has a template_folder configured."
        )

    loader = _nxscript_loader(server)
    return loader(template_name, **context)


# ---------------------------------------------------------------------------
# HTML escaping utility
# ---------------------------------------------------------------------------

def escape_html(text: Any) -> str:
    """Escape text for safe HTML output."""
    if text is None:
        return ""
    return escape(str(text), quote=True)
