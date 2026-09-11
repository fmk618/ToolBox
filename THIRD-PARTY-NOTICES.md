# Third-party notices

## MinerU 3.4.5

FMKTools can optionally invoke the locally installed [MinerU](https://github.com/opendatalab/MinerU) CLI for complex-document parsing. The base installation does not install MinerU; enable it explicitly with `uv sync --extra mineru`. The integration invokes the local `mineru` executable without a shell, uses a temporary output directory, copies only a Markdown result inside that directory, and removes the directory after the conversion. MinerU is not exposed as a public unauthenticated service and the browser cannot select a remote MinerU URL.

MinerU 3.4.5 is distributed under Apache License 2.0 together with additional terms in its distribution. Those terms include attribution requirements for online services and separate commercial licensing conditions above the stated usage thresholds. Review the exact license files shipped with the installed MinerU version before offering a hosted service. MinerU's model weights and transitive dependencies may have separate licenses; they are not relicensed by FMKTools and must be reviewed independently.

The optional integration is a subprocess boundary and does not statically link MinerU into FMKTools. A missing installation, model download failure, timeout, or parsing error falls back to the existing Docling, OpenDataLoader, MarkItDown, and other conversion engines where a route is available.

## Other runtime dependencies

See the dependency and frontend notices for the current licenses of the remaining optional engines and embedded editors. Runtime model providers configured by a user are separate third-party services and receive only the data explicitly submitted by that user.
