from vietdub.cli import build_parser

def test_parser_defaults():
    args = build_parser().parse_args(["https://youtube.com/watch?v=x"])
    assert args.voice == "nu" and args.bg_volume == 0.15
    assert args.whisper_model == "large-v3-turbo" and not args.force

def test_parser_all_flags():
    args = build_parser().parse_args(
        ["URL", "--voice", "nam", "-o", "out.mp4", "--bg-volume", "0.3",
         "--segments", "s.jsonl", "--workdir", "w", "--force"])
    assert args.voice == "nam" and args.output == "out.mp4" and args.force
