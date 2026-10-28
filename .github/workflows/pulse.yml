name: EL CIRCULO SCAN

on:
  schedule:
    - cron: "*/10 * * * *"
  workflow_dispatch:

permissions:
  contents: write

concurrency:
  group: pulse
  cancel-in-progress: false

jobs:
  run:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Revisar tiendas
        run: python pulse.py
        env:
          DISCORD_WEBHOOK: ${{ secrets.DISCORD_WEBHOOK }}
      - name: Guardar datos
        run: |
          git config user.name "pulse-bot"
          git config user.email "pulse-bot@users.noreply.github.com"
          git add data docs/data.json
          git diff --cached --quiet && exit 0
          git commit -q -m "datos $(date -u +%FT%TZ)"
          for i in 1 2 3; do
            git pull -q --rebase origin main && git push -q && exit 0
            sleep 5
          done
          exit 1
