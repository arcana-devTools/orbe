#!/bin/bash
# O X só sobe quando alguém abre o /desktop. No boot ele comia a RAM do chat.
export MALLOC_ARENA_MAX=2
exec python app.py
