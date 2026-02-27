Azure App Service deployment notes

Required files:
- requirements.txt
- startup.txt

App Settings (Configuration):
- HOST=0.0.0.0
- PORT=8080
- MCP_TRANSPORT=streamable_http

Startup Command:
- python mcp-poc.py

MCP endpoint:
- https://<app-name>.azurewebsites.net/mcp
