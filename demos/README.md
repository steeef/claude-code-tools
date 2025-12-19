# Recording Demos

## Record with asciinema

```bash
asciinema rec demo.cast
# Do your demo, then Ctrl+D or type 'exit' to stop
```

## Convert to GIF with agg

```bash
agg --font-size 18 \
    --font-dir ~/Library/Fonts \
    --font-family "Meslo LG L for Powerline" \
    demo.cast demo.gif
```

## Show keystrokes on screen

Use [KeyCastr](https://github.com/keycastr/keycastr) to overlay keystrokes:

```bash
brew install --cask keycastr
open -a KeyCastr
```
