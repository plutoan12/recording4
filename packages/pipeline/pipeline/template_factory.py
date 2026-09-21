"""사용자 이미지 + 시간 자막으로 재사용 가능한 장면 묶음을 생성합니다."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from pipeline.interchange import DEFAULT_TEMPLATE, ae_script, read_subtitles, serialize

PRESETS = {
    "imac27": {
        "asset": "imac27.png",
        "image": [0, 0, 1920, 1080],
        "slot": [383, 85, 1156, 648],
        "font_size": 56,
    },
    "imac24": {
        "asset": "imac24.png",
        "image": [0, 0, 1920, 1080],
        "slot": [454, 125, 1011, 532],
        "font_size": 48,
    },
    "message-board": {
        "asset": "message-board.jpg",
        "image": [240, 135, 1440, 810],
        "slot": [700, 190, 650, 450],
        "font_size": 48,
    },
    "retro-message": {
        "asset": "retro-message.jpg",
        "image": [360, 220, 1200, 642],
        "slot": [1230, 330, 198, 84],
        "font_size": 18,
        "padding": 8,
        "panel": False,
    },
}


def wrap_text(text: str, width: int, size: int) -> str:
    """한글 전각 기준의 보수적인 줄나눔. 출력 간 같은 줄바꿈을 사용합니다."""
    import unicodedata

    capacity = width / size
    lines = []
    for paragraph in text.splitlines():
        line, length = "", 0.0
        for char in paragraph:
            weight = 1 if unicodedata.east_asian_width(char) in ("W", "F") else 0.65
            if length + weight > capacity and line:
                lines.append(line)
                line, length = "", 0.0
            line += char
            length += weight
        lines.append(line)
    return "\n".join(lines)


def scene_data(subs, name: str) -> dict:
    if name not in PRESETS:
        raise ValueError("알 수 없는 템플릿입니다.")
    preset = PRESETS[name]
    cues = []
    for event in subs:
        if event.is_comment or event.is_drawing or not event.plaintext.strip():
            continue
        text = wrap_text(
            event.plaintext, preset["slot"][2] - preset.get("padding", 80), preset["font_size"]
        )
        if len(text.splitlines()) * preset["font_size"] * 1.4 > preset["slot"][3] - preset.get(
            "padding", 50
        ):
            raise ValueError(f"{name}: 자막이 영역을 넘습니다. 문장을 나눠 주세요.")
        cues.append({"start": event.start / 1000, "end": event.end / 1000, "text": text})
    if not cues:
        raise ValueError("표시할 자막이 없습니다.")
    cues.sort(key=lambda c: c["start"])
    if any(b["start"] < a["end"] for a, b in zip(cues, cues[1:], strict=False)):
        raise ValueError("단일 표시 영역에서는 자막을 겹칠 수 없습니다. 시간을 수정하세요.")
    return {
        "version": 1,
        "name": name,
        "width": 1920,
        "height": 1080,
        "fps": 30,
        "duration": max(c["end"] for c in cues) + 0.5,
        **preset,
        "cues": cues,
    }


def preview_html(scene: dict) -> str:
    payload = json.dumps(scene, ensure_ascii=True).replace("<", "\\u003c")
    return """<!doctype html><html lang="ko"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>recording4 템플릿 미리보기</title>
<style>body{margin:0;padding:24px;background:#181820;color:#fff;font-family:Arial,sans-serif}
main{max-width:1280px;margin:auto}canvas{width:100%;background:#eee;border-radius:12px}
.controls{display:flex;gap:16px;align-items:center;margin:20px 0}input{flex:1}
button{padding:12px 24px;border:0;border-radius:8px;background:#ffd0e9;color:#302030}
p{color:#ccc}a{color:#ffd0e9}</style><main><h1>템플릿 미리보기</h1>
<canvas width="1920" height="1080" aria-label="시간에 맞춰 표시되는 자막 장면"></canvas>
<div class="controls"><button id="play">재생</button><label for="time">시간</label>
<input id="time" type="range" min="0" step="0.01"><output id="clock"></output></div>
<p>scene.json에 자막·시간·배치가 저장됩니다. AE에서는 build.jsx를 실행하세요.</p>
<p id="error" role="alert"></p></main><script>
const s=PAYLOAD, canvas=document.querySelector('canvas'),ctx=canvas.getContext('2d');
const slider=document.querySelector('#time'),clock=document.querySelector('#clock');
slider.max=s.duration;let playing=false,last=0,t=0;
const bg=new Image(),frame=new Image();bg.src='assets/pink.jpg';frame.src='assets/'+s.asset;
function draw(){ctx.clearRect(0,0,1920,1080);ctx.drawImage(bg,0,0,1920,1080);
ctx.drawImage(frame,...s.image);const [x,y,w,h]=s.slot;
if(s.panel!==false){ctx.fillStyle='#ffffff';ctx.fillRect(x,y,w,h);}
const cue=s.cues.find(c=>t>=c.start&&t<c.end);
if(cue){ctx.fillStyle='#382333';ctx.font=s.font_size+'px "Apple SD Gothic Neo",sans-serif';
ctx.textAlign='center';ctx.textBaseline='middle';const lines=cue.text.split('\\n');
lines.forEach((line,i)=>ctx.fillText(line,x+w/2,y+h/2+(i-(lines.length-1)/2)*s.font_size*1.4));}
slider.value=t;clock.textContent=t.toFixed(2)+' / '+s.duration.toFixed(2)+'초';}
Promise.all([bg.decode(),frame.decode()]).then(()=>{draw();requestAnimationFrame(tick);})
.catch(e=>{document.querySelector('#error').textContent='이미지 읽기 실패: '+e.message});
function tick(now){if(playing){t=Math.min(s.duration,t+(now-last)/1000);
if(t>=s.duration){playing=false;document.querySelector('#play').textContent='재생';}draw();}
last=now;requestAnimationFrame(tick);}
slider.oninput=()=>{t=Number(slider.value);draw()};
document.querySelector('#play').onclick=()=>{if(t>=s.duration)t=0;playing=!playing;
document.querySelector('#play').textContent=playing?'일시정지':'재생';};
</script></html>""".replace("PAYLOAD", payload)


def scene_jsx(scene: dict, subs) -> str:
    """기존 자막 JSX의 텍스트 레이어에 이미지와 교체 영역을 추가합니다."""
    import copy

    source = copy.deepcopy(subs)
    source.events = []
    import pysubs2

    for cue in scene["cues"]:
        event = pysubs2.SSAEvent(start=round(cue["start"] * 1000), end=round(cue["end"] * 1000))
        event.plaintext = cue["text"]
        source.append(event)
    style = DEFAULT_TEMPLATE | {
        "font": "AppleSDGothicNeo-Regular",
        "size": scene["font_size"],
        "color": "#382333",
        "alignment": 5,
    }
    script = ae_script(source, style)
    s = json.dumps(scene, ensure_ascii=True)
    extra = """
    var scene=SCENE, root=File($.fileName).parent;
    comp.name=scene.name;comp.duration=scene.duration;
    var slot=scene.slot;
    for(var k=1;k<=comp.numLayers;k++) {
      comp.layer(k).property("ADBE Transform Group").property("ADBE Position")
        .setValue([slot[0]+slot[2]/2,slot[1]+slot[3]/2]);
    }
    if(scene.panel!==false){
    var panel=comp.layers.addSolid([1,1,1],"Replaceable screen",
      slot[2],slot[3],1,scene.duration);
    panel.property("ADBE Transform Group").property("ADBE Position")
      .setValue([slot[0]+slot[2]/2,slot[1]+slot[3]/2]);panel.moveToEnd();
    }
    function picture(filename,box){
      var file=new File(root.fsName+"/assets/"+filename);
      if(!file.exists)throw new Error("Missing asset: "+filename);
      var footage=app.project.importFile(new ImportOptions(file));
      var layer=comp.layers.add(footage);layer.outPoint=scene.duration;
      layer.property("ADBE Transform Group").property("ADBE Scale")
        .setValue([100*box[2]/footage.width,100*box[3]/footage.height]);
      layer.property("ADBE Transform Group").property("ADBE Position")
        .setValue([box[0]+box[2]/2,box[1]+box[3]/2]);layer.moveToEnd();
    }
    picture(scene.asset,scene.image);picture("pink.jpg",[0,0,1920,1080]);
""".replace("SCENE", s)
    return script.replace("    comp.openInViewer();", extra + "\n    comp.openInViewer();")


def render_video(scene: dict, folder: Path, font: Path) -> None:
    import imageio_ffmpeg

    if not font.is_file():
        raise ValueError("한글 표시용 글꼴 파일이 없습니다. --font 경로를 지정하세요.")
    # 명령 인자가 아닌 필터에서 경로 이스케이프가 필요하지 않게 단순 상대 경로 사용.
    shutil.copyfile(font, folder / "render-font.ttc")
    x, y, w, h = scene["image"]
    sx, sy, sw, sh = scene["slot"]
    panel = (
        f",drawbox=x={sx}:y={sy}:w={sw}:h={sh}:color=white:t=fill"
        if scene.get("panel", True)
        else ""
    )
    filters = [
        "[0:v]scale=1920:1080,setsar=1[bg]",
        f"[1:v]scale={w}:{h}[fg]",
        f"[bg][fg]overlay={x}:{y}{panel}[v0]",
    ]
    index = 0
    for cue in scene["cues"]:
        lines = cue["text"].splitlines()
        for row, line in enumerate(lines):
            (folder / f"cue-{index}.txt").write_text(line, encoding="utf-8")
            offset = (row - (len(lines) - 1) / 2) * scene["font_size"] * 1.4
            filters.append(
                f"[v{index}]drawtext=fontfile=render-font.ttc:textfile=cue-{index}.txt:"
                f"expansion=none:fontsize={scene['font_size']}:fontcolor=0x382333:"
                f"x={sx}+({sw}-text_w)/2:y={sy}+({sh}-text_h)/2+{offset}:"
                f"enable='gte(t,{cue['start']})*lt(t,{cue['end']})'[v{index+1}]"
            )
            index += 1
    (folder / "render.filter").write_text(";\n".join(filters), encoding="utf-8")
    command = [
        imageio_ffmpeg.get_ffmpeg_exe(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-n",
        "-loop",
        "1",
        "-framerate",
        "30",
        "-i",
        "assets/pink.jpg",
        "-loop",
        "1",
        "-framerate",
        "30",
        "-i",
        f"assets/{scene['asset']}",
        "-filter_complex_script",
        "render.filter",
        "-map",
        f"[v{index}]",
        "-t",
        str(scene["duration"]),
        "-r",
        "30",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "preview.mp4",
    ]
    try:
        subprocess.run(command, cwd=folder, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        raise ValueError("영상 렌더 실패: " + exc.stderr[-1500:]) from exc
    finally:
        (folder / "render-font.ttc").unlink(missing_ok=True)


def _build(
    input_file: Path,
    assets: Path,
    output: Path,
    names: list[str],
    render: bool = False,
    font: Path = Path("/System/Library/Fonts/AppleSDGothicNeo.ttc"),
    encoding: str | None = None,
) -> None:
    subs, warnings = read_subtitles(input_file, encoding)
    scenes = [scene_data(subs, name) for name in names]
    for name in {"pink.jpg"} | {s["asset"] for s in scenes}:
        if not (assets / name).is_file():
            raise ValueError(f"필요한 이미지가 없습니다: {assets/name}")
    output.mkdir(parents=True, exist_ok=False)
    records = []
    for scene in scenes:
        folder = output / scene["name"]
        (folder / "assets").mkdir(parents=True)
        hashes = {}
        for name in ("pink.jpg", scene["asset"]):
            shutil.copy2(assets / name, folder / "assets" / name)
            hashes[name] = hashlib.sha256((assets / name).read_bytes()).hexdigest()
        (folder / "scene.json").write_text(
            json.dumps(scene, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (folder / "preview.html").write_text(preview_html(scene), encoding="utf-8")
        (folder / "build.jsx").write_text(scene_jsx(scene, subs), encoding="utf-8")
        (folder / "captions.srt").write_text(serialize(subs, "srt")[0], encoding="utf-8")
        if render:
            render_video(scene, folder, font)
        records.append({"template": scene["name"], "assets": hashes, "rendered": render})
    report = {
        "version": 1,
        "templates": records,
        "warnings": warnings,
        "limits": [
            "MP4는 무음이며 자막과 배경이 합쳐진 영상입니다.",
            "AE JSX는 편집 가능한 레이어를 생성합니다. 앱 내 실행 검증은 별도입니다.",
            "MOGRT·CapCut·Fusion 네이티브 템플릿은 생성하지 않습니다.",
            "이미지 원본을 보존하며 직사각형 자막 영역을 덮어 배치합니다.",
        ],
    }
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    links = "".join(
        f'<li><a href="{html.escape(n)}/preview.html">{html.escape(n)}</a></li>' for n in names
    )
    (output / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><h1>recording4 템플릿</h1>' "<ul>" + links + "</ul>",
        encoding="utf-8",
    )


def build(
    input_file,
    assets,
    output,
    names,
    render=False,
    font=Path("/System/Library/Fonts/AppleSDGothicNeo.ttc"),
    encoding=None,
):
    if output.exists():
        raise ValueError("기존 출력은 덮어쓰지 않습니다. 새 폴더를 지정하세요.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".template-", dir=output.parent) as temp:
        staging = Path(temp) / "result"
        _build(input_file, assets, staging, names, render, font, encoding)
        staging.rename(output)


def main(argv=None):
    parser = argparse.ArgumentParser(description="이미지 템플릿 + 자막 자동 제작")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--assets", type=Path, default=Path(".runtime/template-assets"))
    parser.add_argument("--template", choices=[*PRESETS, "all"], default="all")
    parser.add_argument("--render", action="store_true", help="편집기 공용 MP4도 생성")
    parser.add_argument("--encoding")
    parser.add_argument(
        "--font", type=Path, default=Path("/System/Library/Fonts/AppleSDGothicNeo.ttc")
    )
    args = parser.parse_args(argv)
    try:
        build(
            args.input,
            args.assets,
            args.output,
            list(PRESETS) if args.template == "all" else [args.template],
            args.render,
            args.font,
            args.encoding,
        )
    except (ValueError, OSError) as exc:
        parser.exit(2, f"제작 실패: {exc}\n")
    print(f"생성 완료: {args.output}/index.html")


if __name__ == "__main__":
    main()
