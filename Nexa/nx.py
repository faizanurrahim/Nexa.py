
from html import escape


class Element:
    def __init__(self, tag, props=None, *children):
        self.tag = tag
        self.props = props or {}
        self.children = children

    def render(self):
        attrs = "".join(
            f' {key}="{escape(str(value), quote=True)}"'
            for key, value in self.props.items()
            if value is not None and not key.startswith("on")
        )

        content = "".join(
            child.render()
            if isinstance(child, (Element, Fragment))
            else escape(str(child))
            for child in self.children
            if child is not None
        )

        return f"<{self.tag}{attrs}>{content}</{self.tag}>"


class Fragment:
    def __init__(self, *children):
        self.children = children

    def render(self):
        return "".join(
            child.render()
            if isinstance(child, (Element, Fragment))
            else escape(str(child))
            for child in self.children
            if child is not None
        )


class App:
    def __init__(self, name="Nexa"):
        self.name = name

    def render(self, component):
        result = component()
        return result.render()
