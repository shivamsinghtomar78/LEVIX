"""The interactive dashboard: a launcher, not a second engine.

Nothing in here reimplements a module. A selection builds the same argv you would type
(`levix monitor live`), suspends Textual so exactly one application owns the terminal,
and runs it as a child process. That keeps the exit code, the dependency gate and the
history log identical to the keyboard path.

Importing this package pulls in Textual, so only `levix dashboard` reaches it - the
`levix --help` path never does.
"""
