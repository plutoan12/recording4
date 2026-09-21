"""자막 형식 교환과 편집기용 묶음. 기존 렌더링·승인 경로와 독립적입니다."""

from __future__ import annotations

import argparse
import codecs
import copy
import json
import math
import re
import shutil
import tempfile
from pathlib import Path

import pysubs2
from pysubs2.formats.sami import SAMIParser

INPUTS = {
    ".srt": "srt",
    ".vtt": "vtt",
    ".ass": "ass",
    ".ssa": "ssa",
    ".smi": "sami",
    ".sami": "sami",
    ".ttml": "ttml",
    ".json": "json",
}
OUTPUTS = {k: v for k, v in INPUTS.items() if v != "sami"}
TARGETS = ("premiere", "after-effects", "capcut", "davinci", "all")
DEFAULT_TEMPLATE = dict(
    version=1,
    font="Arial",
    size=52,
    color="#FFFFFF",
    alignment=2,
    margin_v=80,
    width=1920,
    height=1080,
)


def parse_sami(text: str) -> pysubs2.SSAFile:
    # pysubs2 1.8의 기본 SAMI reader는 끝을 글자 수로 추정합니다.
    # 다음 SYNC(빈 자막 포함)를 실제 종료 시각으로 사용합니다.
    parser = SAMIParser()
    parser.feed(text)
    parser.close_sync_element()
    result = pysubs2.SSAFile()
    for index, item in enumerate(parser.sync_elements):
        if not item.text.strip():
            continue
        if index + 1 == len(parser.sync_elements):
            raise ValueError("SMI 마지막 자막 뒤에 종료 시각을 나타내는 빈 SYNC가 필요합니다.")
        event = pysubs2.SSAEvent(
            start=item.start_ms,
            end=parser.sync_elements[index + 1].start_ms,
            text=item.text.strip().replace("\n", r"\N"),
        )
        result.append(event)
    return result


def load_template(path: Path | None) -> dict:
    data = json.loads(path.read_text(encoding="utf-8-sig")) if path else {}
    if not isinstance(data, dict) or set(data) - set(DEFAULT_TEMPLATE):
        raise ValueError("템플릿은 지원 필드만 담은 JSON 객체여야 합니다.")
    result = DEFAULT_TEMPLATE | data
    if type(result["version"]) is not int or result["version"] != 1:
        raise ValueError("템플릿 version은 1이어야 합니다.")
    if not isinstance(result["font"], str) or not result["font"].strip():
        raise ValueError("font에 글꼴 이름을 넣으세요.")
    if not isinstance(result["color"], str) or not re.fullmatch(
        r"#[0-9a-fA-F]{6}", result["color"]
    ):
        raise ValueError("color는 #RRGGBB 형식입니다.")
    for name, low, high in (
        ("size", 1, 1000),
        ("alignment", 1, 9),
        ("width", 16, 16384),
        ("height", 16, 16384),
        ("margin_v", 0, 16384),
    ):
        value = result[name]
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"{name}: {low}~{high} 범위의 정수를 넣으세요.")
    if result["margin_v"] >= result["height"] / 2:
        raise ValueError("margin_v는 화면 높이의 절반보다 작아야 합니다.")
    return result


def read_subtitles(path: Path, encoding: str | None = None) -> tuple[pysubs2.SSAFile, list[str]]:
    fmt = INPUTS.get(path.suffix.lower())
    if not fmt:
        raise ValueError("지원 입력: SRT, VTT, ASS, SSA, SMI/SAMI, TTML, pysubs2 JSON")
    raw = path.read_bytes()
    if len(raw) > 20_000_000:
        raise ValueError("자막 파일은 20 MB 이하만 받습니다.")
    if encoding is None:
        encoding = "utf-8-sig"
        for bom, name in (
            (codecs.BOM_UTF32_LE, "utf-32"),
            (codecs.BOM_UTF32_BE, "utf-32"),
            (codecs.BOM_UTF16_LE, "utf-16"),
            (codecs.BOM_UTF16_BE, "utf-16"),
        ):
            if raw.startswith(bom):
                encoding = name
                break
    try:
        text = raw.decode(encoding)
    except (UnicodeError, LookupError) as exc:
        raise ValueError("인코딩 오류: 한국어 옛 자막은 --encoding cp949를 쓰세요.") from exc
    try:
        subs = parse_sami(text) if fmt == "sami" else pysubs2.SSAFile.from_string(text, format_=fmt)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"{fmt} 파일을 읽지 못했습니다: {type(exc).__name__}") from exc
    if not subs.events:
        raise ValueError("읽을 수 있는 자막이 없습니다.")
    notes = []
    if fmt not in ("ass", "ssa", "json"):
        notes.append("입력 파서가 지원하지 않는 위치·스타일·메타데이터는 손실될 수 있습니다.")
    if fmt == "sami":
        notes.append("SMI 다국어 클래스 선택은 미지원입니다. 단일 언어 SMI를 사용하세요.")
    latest_end = 0
    for index, event in enumerate(subs.events, 1):
        if event.is_comment:
            continue
        if (
            not all(
                isinstance(v, int | float) and math.isfinite(v) for v in (event.start, event.end)
            )
            or event.start < 0
            or event.end <= event.start
        ):
            raise ValueError(f"{index}번 자막 시간이 잘못되었습니다.")
    for index, event in enumerate(sorted(subs.events, key=lambda e: e.start), 1):
        if not event.is_comment and not event.is_drawing:
            if event.start < latest_end:
                notes.append(f"{index}번 자막이 앞 자막과 겹칩니다. 시간을 유지했습니다.")
            latest_end = max(latest_end, event.end)
    return subs, notes


def apply_template(subs: pysubs2.SSAFile, template: dict) -> pysubs2.SSAFile:
    """명시적으로 요청한 템플릿은 기존 스타일·인라인 효과를 대체합니다."""
    result = copy.deepcopy(subs)
    color = template["color"][1:]
    result.styles = {
        "Default": pysubs2.SSAStyle(
            fontname=template["font"],
            fontsize=template["size"],
            primarycolor=pysubs2.Color(*(int(color[i : i + 2], 16) for i in (0, 2, 4))),
            alignment=pysubs2.Alignment(template["alignment"]),
            marginv=template["margin_v"],
        )
    }
    result.info.update(PlayResX=str(template["width"]), PlayResY=str(template["height"]))
    result.events = [e for e in result if not e.is_comment and not e.is_drawing]
    for event in result:
        event.plaintext = event.plaintext
        event.style = "Default"
        event.marginl = event.marginr = event.marginv = 0
        event.effect = ""
    return result


def serialize(subs: pysubs2.SSAFile, fmt: str) -> tuple[str, list[str]]:
    notes = []
    result = copy.deepcopy(subs)
    if fmt not in ("ass", "ssa", "json"):
        notes.append("이 출력은 ASS 위치·모션·스타일을 완전히 보존하지 않습니다.")
        result.events = [e for e in result if not e.is_comment and not e.is_drawing]
        if fmt in ("srt", "vtt"):
            for event in result:
                event.plaintext = event.plaintext
                event.style = "Default"
            result.styles = {"Default": pysubs2.SSAStyle()}
            notes.append(
                "SRT/VTT는 시간·텍스트·줄바꿈만 출력합니다. 스타일은 편집기에서 적용하세요."
            )
    if fmt == "ssa":
        notes.append("ASS 전용 기능은 SSA에서 동일하게 재현되지 않을 수 있습니다.")
    return result.to_string(fmt), notes


def ae_script(subs: pysubs2.SSAFile, template: dict) -> str:
    rows = [
        {"start": e.start / 1000, "end": e.end / 1000, "text": e.plaintext}
        for e in subs
        if not e.is_comment and not e.is_drawing and e.plaintext.strip()
    ]
    if not rows:
        raise ValueError("After Effects에 만들 텍스트 자막이 없습니다.")
    # ASCII JSON은 따옴표·백슬래시·U+2028까지 JS 소스로 안전하게 인코딩합니다.
    payload = json.dumps({"cues": rows, "style": template}, ensure_ascii=True)
    return """// recording4: File > Scripts > Run Script File
(function () {
  var data = PAYLOAD;
  app.beginUndoGroup("recording4 captions");
  try {
    if (!app.project) app.newProject();
    var s = data.style, duration = 1;
    for (var i = 0; i < data.cues.length; i++)
      duration = Math.max(duration, data.cues[i].end);
    var comp = app.project.items.addComp("recording4 captions", s.width, s.height,
                                         1, duration, 30);
    var col = (s.alignment - 1) % 3;
    var row = Math.floor((s.alignment - 1) / 3);
    var rgb = [parseInt(s.color.substr(1,2),16)/255,
               parseInt(s.color.substr(3,2),16)/255,
               parseInt(s.color.substr(5,2),16)/255];
    for (var j = 0; j < data.cues.length; j++) {
      var cue = data.cues[j], layer = comp.layers.addText(cue.text);
      layer.inPoint = cue.start; layer.outPoint = cue.end;
      var prop = layer.property("ADBE Text Properties").property("ADBE Text Document");
      var doc = prop.value;
      doc.font = s.font; doc.fontSize = s.size;
      doc.applyFill = true; doc.fillColor = rgb; doc.applyStroke = false;
      doc.justification = col === 0 ? ParagraphJustification.LEFT_JUSTIFY :
        col === 1 ? ParagraphJustification.CENTER_JUSTIFY : ParagraphJustification.RIGHT_JUSTIFY;
      prop.setValue(doc);
      var rect = layer.sourceRectAtTime(cue.start, false);
      layer.property("ADBE Transform Group").property("ADBE Anchor Point").setValue(
        [rect.left + rect.width * col / 2, rect.top + rect.height * (1 - row / 2)]);
      layer.property("ADBE Transform Group").property("ADBE Position").setValue(
        [col === 0 ? 40 : col === 1 ? s.width/2 : s.width-40,
         row === 0 ? s.height-s.margin_v : row === 1 ? s.height/2 : s.margin_v]);
    }
    comp.openInViewer();
  } catch (err) { alert("recording4: " + err.toString()); }
  finally { app.endUndoGroup(); }
})();
""".replace("PAYLOAD", payload)


def make_bundle(
    subs: pysubs2.SSAFile, destination: Path, target: str, template: dict, notes: list[str]
) -> list[str]:
    if destination.exists():
        raise ValueError("출력 폴더가 이미 있습니다. 새 폴더 이름을 지정하세요.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    selected = TARGETS[:-1] if target == "all" else (target,)
    files = {
        "archive.ass": subs.to_string("ass"),
        "archive.json": subs.to_string("json"),
        "template.json": json.dumps(template, ensure_ascii=False, indent=2),
    }
    warnings = list(notes)
    for editor in selected:
        if editor == "after-effects":
            files[f"{editor}/captions.jsx"] = ae_script(subs, template)
            warnings.append(
                "After Effects는 공통 템플릿으로 새 30fps 컴포지션을 만듭니다. "
                "원본 ASS 효과·레이어별 스타일은 보존하지 않습니다. 폰트는 확인하세요."
            )
        else:
            files[f"{editor}/captions.srt"], extra = serialize(subs, "srt")
            warnings.extend(extra)
    warnings.append("MOGRT/AEP, CapCut 프로젝트, Resolve DRP/Fusion 템플릿 간 변환은 미지원입니다.")
    warnings = list(dict.fromkeys(warnings))
    files["report.json"] = json.dumps(
        {"targets": selected, "warnings": warnings, "files": sorted(files)},
        ensure_ascii=False,
        indent=2,
    )
    files["README.txt"] = (
        "프리미어: captions.srt를 가져와 시퀀스에 배치합니다.\n"
        "캡컷 Desktop/Web: 자막 가져오기에서 captions.srt를 선택합니다.\n"
        "다빈치: captions.srt를 가져와 자막 트랙에 배치합니다.\n"
        "After Effects: File > Scripts > Run Script File에서 captions.jsx를 실행합니다.\n"
        "template.json은 recording4 전용 스타일 설정이며 각 편집기의 네이티브 템플릿이 아닙니다.\n"
        "세 SRT 대상의 폰트/색/배치는 편집기 안에서 적용하세요.\n\n" + "\n".join(warnings)
    )
    staging = Path(tempfile.mkdtemp(prefix=".captions-", dir=destination.parent))
    try:
        for name, content in files.items():
            file = staging / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(content, encoding="utf-8")
        staging.rename(destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="자막 형식 변환 / 네 편집기용 자막 묶음")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path, help="출력 파일 또는 --target 묶음 폴더")
    parser.add_argument("--encoding", help="UTF-8/BOM 외 입력 인코딩. 예: cp949")
    parser.add_argument("--template", type=Path, help="recording4 스타일 JSON (기존 스타일 대체)")
    parser.add_argument("--target", choices=TARGETS)
    args = parser.parse_args(argv)
    try:
        subs, notes = read_subtitles(args.input, args.encoding)
        template = load_template(args.template)
        if args.template:
            subs = apply_template(subs, template)
            notes.append("요청한 공통 템플릿으로 기존 스타일·인라인 효과를 대체했습니다.")
        if args.target:
            notes = make_bundle(subs, args.output, args.target, template, notes)
        else:
            fmt = OUTPUTS.get(args.output.suffix.lower())
            if not fmt:
                raise ValueError("지원 출력: SRT, VTT, ASS, SSA, TTML, pysubs2 JSON. SMI는 입력만.")
            content, extra = serialize(subs, fmt)
            notes.extend(extra)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            # 원본/기존 출력은 덮어쓰지 않습니다.
            with args.output.open("x", encoding="utf-8") as file:
                file.write(content)
        print(
            json.dumps(
                {"output": str(args.output), "warnings": notes}, ensure_ascii=False, indent=2
            )
        )
    except (ValueError, OSError, pysubs2.exceptions.Pysubs2Error) as exc:
        parser.exit(2, f"변환 실패: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
