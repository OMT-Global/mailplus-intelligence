# Update documentation to reflect new atomic commit behavior
## Offline Incremental Sync

The offline incremental sync process has been updated to commit record mutations and checkpoint advancement atomically.

### Benefits

* Improved data consistency and integrity
* Enhanced reliability and fault tolerance
* Better support for concurrent access and updates

### Changes

* Per-record savepoints or an equivalent transaction boundary have been implemented
* Record mutations and checkpoint advancement are now committed atomically
* Distinguishing between idempotency key and uniqueness/constraint failures has been improved

### Impact

* Improved overall system reliability and performance
* Enhanced support for concurrent access and updates
* Better data consistency and integrity