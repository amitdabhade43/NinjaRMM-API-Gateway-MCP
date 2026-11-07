from ninja_mcp.compat_tools import register_compat_tools


class FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self):
        def register(function):
            self.tools[function.__name__] = function
            return function
        return register


def test_register_compat_tools_exposes_all_seven_names():
    fake = FakeMCP()
    register_compat_tools(
        fake,
        spec_getter=lambda: None,
        execute=lambda *args, **kwargs: None,
        match_template=lambda *args, **kwargs: None,
    )

    assert set(fake.tools) == {
        "find_endpoint",
        "describe_endpoint",
        "call",
        "raw_call",
        "memory_save",
        "memory_list",
        "memory_delete",
    }
