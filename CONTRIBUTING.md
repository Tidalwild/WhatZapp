# Contributing

Issues and pull requests are welcome on this repository. Do not send private chat transcripts, phone numbers, webhook URLs, or credentials.

## Tests

From `web/`:

```sh
npm ci
npm test
npx tsc --noEmit
npm run test:browser
```

From the repository root:

```sh
python3 -m unittest discover -s tests/wake -q
python3 scripts/privacy_scan.py
```

Browser tests use a local fixture page. They do not log into WhatsApp.

## Privacy

Fixtures use synthetic labels such as `contact-a`. Do not add a real contact name, a live webhook, a home-directory path, or a transcript. `scripts/privacy_scan.py` checks tracked files. `scripts/package_release.sh` builds a git archive and runs that scan.

## License

By contributing, you agree that your contribution is under the MIT license in `LICENSE`. Do not remove third-party license notices.
