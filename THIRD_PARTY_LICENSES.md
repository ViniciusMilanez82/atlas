# Licenças de terceiros (ambiente de desenvolvimento)

Gerado a partir do venv em 2026-09-23. Dependências de runtime: jsonschema, PyYAML (e suas transitivas). As demais são ferramentas de desenvolvimento.

| Pacote | Versão | Licença |
| --- | --- | --- |
| ast_serialize | 0.11.2 | MIT |
| attrs | 26.1.0 | MIT |
| cffi | 2.1.1 | MIT-0 |
| colorama | 0.4.6 | BSD License |
| cryptography | 50.0.1 | Apache-2.0 OR BSD-3-Clause |
| iniconfig | 2.3.0 | MIT |
| jsonschema | 4.26.0 | MIT |
| jsonschema-specifications | 2025.9.1 | MIT |
| librt | 0.15.0 | MIT |
| mypy | 2.3.1 | MIT |
| mypy_extensions | 1.1.0 | MIT |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| pathspec | 1.1.1 | Mozilla Public License 2.0 (MPL 2.0) |
| pip | 26.2.1 | MIT |
| pluggy | 1.6.0 | MIT |
| pycparser | 3.0 | BSD-3-Clause |
| Pygments | 2.21.0 | BSD-2-Clause |
| pytest | 9.1.1 | MIT |
| PyYAML | 6.0.3 | MIT |
| referencing | 0.37.0 | MIT |
| rpds-py | 2026.6.3 | MIT |
| ruff | 0.16.8 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |

## Dependências de runtime adicionadas em 2026-09-24 (ADR-016, extração de documentos)

| Pacote | Versão | Licença | Uso |
| --- | --- | --- | --- |
| pypdf | 6.19.0 | BSD-3-Clause | texto por página de PDF |
| python-docx | 1.2.0 | MIT | parágrafos, tabelas, cabeçalhos de DOCX |
| openpyxl | 3.1.5 | MIT | células, fórmulas e valores salvos de XLSX |
| python-pptx | 1.0.2 | MIT | slides, tabelas e notas de PPTX |
| lxml | 6.1.3 | BSD-3-Clause | dependência de python-docx/python-pptx |
| et-xmlfile | 2.0.0 | MIT | dependência de openpyxl |
| Pillow | 12.3.0 | MIT-CMU (HPND) | dependência de python-pptx |
| XlsxWriter | 3.2.9 | BSD-2-Clause | dependência de python-pptx |
| types-openpyxl | 3.1.5.20260827 | Apache-2.0 | stubs de tipo (somente desenvolvimento) |

