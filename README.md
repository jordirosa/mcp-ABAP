# mcp-ABAP

Servidor MCP para trabajar con sistemas SAP ABAP desde clientes compatibles con Model Context Protocol. Expone herramientas para sesiones ADT, objetos de desarrollo ABAP, DDIC, transportes, paquetes, data preview, ABAP Unit y automatizacion local de SAP GUI/WebGUI.

El proyecto esta pensado para ejecucion local. Las credenciales y sistemas SAP se configuran en `.env`, que no debe versionarse.

## Requisitos

- Python 3.11 o superior.
- Acceso HTTP(S) al endpoint ADT del sistema SAP.
- Usuario SAP con permisos para las operaciones que se quieran ejecutar.
- En Windows, SAP GUI instalado si se van a usar las tools de SAP GUI.
- Playwright/Chromium si se van a usar las tools de SAP WebGUI.

## Instalacion

1. Clonar el repositorio:

   ```powershell
   git clone https://github.com/jordirosa/mcp-ABAP.git
   cd mcp-ABAP
   ```

2. Crear y activar un entorno virtual:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. Instalar dependencias:

   ```powershell
   pip install -r requirements.txt
   ```

4. Crear la configuracion local:

   ```powershell
   copy .env.example .env
   ```

5. Editar `.env` y completar `SAP_SYSTEMS_JSON` con los sistemas SAP disponibles. Como minimo, cada sistema debe definir:

   - `id`
   - `name`
   - `server`
   - `user`
   - `password`
   - `client`
   - `language`
   - `verify_ssl`

6. Arrancar el servidor en modo HTTP:

   ```powershell
   .\start.bat
   ```

   Por defecto se publica en:

   ```text
   http://127.0.0.1:8081/mcp/abap
   ```

7. Abrir el dashboard local:

   ```text
   http://127.0.0.1:8081/mcp/abap/dashboard
   ```

   Desde el dashboard se puede editar la configuracion de sistemas SAP, revisar clientes MCP locales y registrar el servidor en clientes soportados.

## Ejecucion

Tambien se puede arrancar directamente con Python:

```powershell
python server.py --transport http --host 127.0.0.1 --port 8081 --path /mcp/abap --log-level info
```

Para integraciones que esperan transporte `stdio`:

```powershell
python server.py --transport stdio
```

## Configuracion SAP

La configuracion vive en `.env`. El formato recomendado es `SAP_SYSTEMS_JSON`, que permite declarar varios sistemas:

```env
SAP_SYSTEMS_JSON='[
  {
    "id": "DEV",
    "name": "Servidor de Desarrollo",
    "type": "Desarrollo",
    "server": "https://host-dev:port",
    "user": "tu_usuario_dev",
    "password": "tu_password_dev",
    "client": "500",
    "language": "EN",
    "verify_ssl": false,
    "sap_gui_connection_name": "Nombre en SAP Logon",
    "sap_webgui_url": "https://host-dev:port/sap/bc/gui/sap/its/webgui"
  }
]'
```

Notas:

- `.env` esta ignorado por Git.
- `.env.example` si se versiona y sirve como plantilla.
- `sap_gui_connection_name` solo es necesario para las tools de SAP GUI.
- `sap_webgui_url` solo es necesario para las tools de SAP WebGUI.
- Si SAP GUI no esta en el `PATH`, se puede definir `SAP_GUI_EXECUTABLE_PATH`.

## Tools

### Conexion y sistemas

- `sap_systems_list`
- `login`
- `logout`

### SAP GUI (experimental)

Estas tools usan SAP GUI Scripting local. Requieren Windows, SAP GUI instalado, scripting habilitado en servidor/cliente y una entrada valida en SAP Logon.

- `sap_gui_sessions_list`
- `sap_gui_session_open`
- `sap_gui_session_close`
- `sap_gui_session_screenshot`
- `sap_gui_session_inspect`
- `sap_gui_session_inspect_to_file`
- `sap_gui_session_read_message`
- `sap_gui_session_actions`
- `sap_gui_recording_start`
- `sap_gui_recording_stop`

### SAP WebGUI (experimental)

Estas tools automatizan SAP WebGUI con Playwright/Chromium. Son utiles para flujos visuales, inspeccion de pantalla y grabaciones, pero pueden depender del HTML generado por cada sistema SAP.

- `sap_webgui_sessions_list`
- `sap_webgui_session_open`
- `sap_webgui_session_close`
- `sap_webgui_snapshot`
- `sap_webgui_screenshot`
- `sap_webgui_click`
- `sap_webgui_type`
- `sap_webgui_press_key`
- `sap_webgui_fill_form`
- `sap_webgui_navigate`
- `sap_webgui_recording_start`
- `sap_webgui_recording_stop`

### Knowledge (experimental)

Estas tools mantienen una base de conocimiento local en `db/documents` y un indice Chroma local en `db/chroma`. El contenido generado en runtime no debe versionarse salvo que se quiera publicar expresamente.

- `knowledge_upsert_document`
- `knowledge_search`
- `knowledge_get_document`

### Programas e includes

- `source_program_create`
- `source_program_read`
- `source_program_lock`
- `source_program_unlock`
- `source_program_update`
- `source_program_delete`
- `source_program_read_to_file`
- `source_program_write_from_file`
- `source_program_symbols_read`
- `source_program_symbols_update`
- `source_program_symbols_read_to_file`
- `source_program_symbols_write_from_file`
- `source_program_include_create`
- `source_program_include_read`
- `source_program_include_lock`
- `source_program_include_unlock`
- `source_program_include_update`
- `source_program_include_delete`
- `source_program_include_read_to_file`
- `source_program_include_write_from_file`

### Clases e interfaces

- `source_class_create`
- `source_class_read`
- `source_class_lock`
- `source_class_unlock`
- `source_class_update`
- `source_class_delete`
- `source_class_read_to_file`
- `source_class_write_from_file`
- `source_class_symbols_read`
- `source_class_symbols_update`
- `source_class_symbols_read_to_file`
- `source_class_symbols_write_from_file`
- `source_class_testclasses_create`
- `source_class_testclasses_read`
- `source_class_testclasses_update`
- `source_class_testclasses_read_to_file`
- `source_class_testclasses_write_from_file`
- `source_interface_create`
- `source_interface_read`
- `source_interface_lock`
- `source_interface_unlock`
- `source_interface_update`
- `source_interface_delete`
- `source_interface_read_to_file`
- `source_interface_write_from_file`

### Grupos de funciones, modulos e includes

- `source_function_group_create`
- `source_function_group_read`
- `source_function_group_lock`
- `source_function_group_unlock`
- `source_function_group_update`
- `source_function_group_delete`
- `source_function_group_read_to_file`
- `source_function_group_write_from_file`
- `source_function_group_symbols_read`
- `source_function_group_symbols_update`
- `source_function_group_symbols_read_to_file`
- `source_function_group_symbols_write_from_file`
- `source_function_module_create`
- `source_function_module_read`
- `source_function_module_lock`
- `source_function_module_unlock`
- `source_function_module_update`
- `source_function_module_delete`
- `source_function_module_read_to_file`
- `source_function_module_write_from_file`
- `source_function_include_create`
- `source_function_include_read`
- `source_function_include_lock`
- `source_function_include_unlock`
- `source_function_include_update`
- `source_function_include_delete`
- `source_function_include_read_to_file`
- `source_function_include_write_from_file`

### DDIC y CDS

- `ddic_table_create`
- `ddic_table_read`
- `ddic_table_update`
- `ddic_table_delete`
- `ddic_table_read_to_file`
- `ddic_table_write_from_file`
- `ddic_table_db_settings_read`
- `ddic_table_db_settings_update`
- `ddic_table_db_settings_read_to_file`
- `ddic_table_db_settings_write_from_file`
- `ddic_dataelement_create`
- `ddic_dataelement_read`
- `ddic_dataelement_update`
- `ddic_dataelement_delete`
- `ddic_dataelement_read_to_file`
- `ddic_dataelement_write_from_file`
- `ddic_domain_create`
- `ddic_domain_read`
- `ddic_domain_update`
- `ddic_domain_delete`
- `ddic_domain_read_to_file`
- `ddic_domain_write_from_file`
- `ddic_ddl_source_create`
- `ddic_ddl_source_read`
- `ddic_ddl_source_lock`
- `ddic_ddl_source_unlock`
- `ddic_ddl_source_update`
- `ddic_ddl_source_delete`
- `ddic_ddl_source_read_to_file`
- `ddic_ddl_source_write_from_file`

### Paquetes, transportes y activacion

- `package_create`
- `package_read`
- `package_update`
- `package_delete`
- `cts_transport_check`
- `cts_transport_create`
- `cts_transport_read`
- `cts_transport_update`
- `cts_transport_delete`
- `cts_transport_read_to_file`
- `cts_transport_write_from_file`
- `activation_activate`

### Busqueda e informacion del repositorio

- `info_repository_search`

### Data Preview

- `datapreview_metadata`
- `datapreview_table_contents`
- `datapreview_run_query`
- `datapreview_table_contents_to_file`
- `datapreview_run_query_to_file`

### Checkruns y ABAP Unit

- `checkrun_syntax_check`
- `abapunit_run`
- `abapunit_coverage_query`
- `abapunit_coverage_statements`

## Desarrollo

Ejecutar tests unitarios:

```powershell
pytest tests/unit
```

Ejecutar todos los tests:

```powershell
pytest
```

Los tests de integracion requieren acceso real a un sistema SAP configurado.

## Licencia

Este proyecto esta publicado bajo licencia MIT. Ver `LICENSE`.
