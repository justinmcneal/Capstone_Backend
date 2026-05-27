.PHONY: migrate-dry migrate-apply verify run-workflow

migrate-dry:
	python scripts/migrate_media_to_s3.py --dry-run --prefix documents

migrate-apply:
	python scripts/migrate_media_to_s3.py --confirm --prefix documents --apply-db

verify:
	python scripts/migration_verifier.py --report migration_report.json --prefix documents

run-workflow:
	gh workflow run run-staging-migration.yml --ref main
