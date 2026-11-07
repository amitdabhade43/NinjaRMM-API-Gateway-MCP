from . import server
from .compat_tools import register_compat_tools

# Register familiar tool names without replacing the existing validated Gateway.
register_compat_tools(
    server.mcp,
    server._spec,
    server._execute,
    server._match_template,
)


def main() -> None:
    server.main()


if __name__ == "__main__":
    main()
