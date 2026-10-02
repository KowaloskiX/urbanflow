"""Passenger counting at a tram doorway.

Separate from `backend/` on purpose. This runs on a device bolted above a door, where the
dependencies are a camera and a model, and the backend runs on a server, where they are a
database and an HTTP stack. Merging them would put several gigabytes of CUDA wheels into the
API image and a database driver onto a Raspberry Pi.

What connects them is the ingest contract, nothing else: this package speaks
`POST /api/v1/ingest/passages` on the UrbanFlow backend, with a device key.
"""
