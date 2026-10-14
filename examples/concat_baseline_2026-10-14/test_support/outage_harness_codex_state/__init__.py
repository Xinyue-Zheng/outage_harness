"""Test double for the internal package.

The internal `outage_harness_codex_state` package is not available outside the
internal environment. This package provides only what the wiring modules
import from it: the radio helpers and the skill resource. Replace it with the
real package when the modules move inside.
"""
