# ServiceNow MCP Server (`snow-mcp`)

[![PyPI version](https://badge.fury.io/py/snow-mcp.svg)](https://badge.fury.io/py/snow-mcp)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A comprehensive, production-ready, and extensible MCP (Machine-Conversation Protocol) server for interacting with a ServiceNow instance. This package provides a rich set of pre-built tools for managing nearly every aspect of ITSM, ITOM, and App Dev within ServiceNow, all callable via a simple, unified interface.

It allows developers and automation engineers to build powerful client applications, scripts, and AI agents that can perform complex, multi-step operations in ServiceNow without needing to handle the intricacies of the REST API directly.

## Features

- **Extensive Tool Library:** Over 60 pre-built tools covering Incidents, Changes, Users, Service Catalog, Projects, and much more.
- **Modular and Organized:** Tools are logically grouped into modules for clarity and extensibility.
- **Production-Ready:** All tools include robust input validation and clear schemas powered by Pydantic.
- **Easy to Use:** Packaged as a standard Python library and installable via `pip`.
- **Self-Documenting:** A built-in CLI allows you to list all available tools directly from your terminal.
- **Claude Desktop Integration:** Seamlessly integrates with Claude Desktop for AI-powered ServiceNow automation.

## Authentication

The server supports basic authentication with ServiceNow. Make sure your API user has the necessary roles and permissions for the operations you want to perform:

- **itil**: Basic ITSM operations (incidents, changes, requests)
- **catalog_admin**: Service catalog management
- **user_admin**: User and group management
- **admin**: Full administrative access

## Rate Limiting

ServiceNow enforces rate limits on API calls. The server includes built-in retry logic with exponential backoff to handle temporary rate limit errors gracefully.


## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.



## Changelog

### v1.0.0
- Initial release with 60+ tools
- Support for ITSM, ITOM, and App Dev operations
- Complete documentation and examples