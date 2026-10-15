"""Dynamic component lifecycle management for s0ma.

Provides runtime create, update, and remove operations with
verification integration and rollback on failure.

All operations:
1. Validate the operation against the current self-model
2. Perform the mutation (register/unregister/replace)
3. Run structural verification on the affected component
4. Roll back if verification fails

Transactional operations wrap multiple lifecycle mutations in a
single atomic context, rolling back all changes on any failure.

Usage:
    from s0ma.lifecycle import LifecycleManager

    lm = LifecycleManager(registry)
    lm.update_component("MyService", intent="Updated intent")
    lm.remove_component("OldService")

    # Transactional multi-step operations:
    with lm.transaction() as txn:
        txn.create_component(source, spec, target_dir=path)
        txn.update_component("Foo", intent="New intent")
        txn.remove_component("Bar", force=True)
"""

from s0ma.lifecycle.manager import LifecycleManager
from s0ma.lifecycle.transaction import TransactionContext

__all__ = ["LifecycleManager", "TransactionContext"]
