"""Generate docs/hermes-account-pool.pdf, the Indonesian guide for the account-pool plugin.

    python3 docs/make_doc.py        # needs reportlab and the DejaVu fonts

Example output is based on real runs, with the accounts renamed (alice@example.com, ...).
"""
import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (CondPageBreak, Image, KeepTogether, PageBreak, Paragraph, Preformatted,
                                SimpleDocTemplate, Spacer, Table, TableStyle)
from reportlab.platypus.tableofcontents import TableOfContents

VERSION = "4.0.1"
REPO = "github.com/roqianjas/hermes-account-pool"
FOOTER = f"Hermes plugin account-pool {VERSION} · {REPO}"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hermes-account-pool.pdf")
SHOTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshots")

D = "/usr/share/fonts/truetype/dejavu/"
pdfmetrics.registerFont(TTFont("Sans", D + "DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("Sans-Bold", D + "DejaVuSans-Bold.ttf"))
pdfmetrics.registerFont(TTFont("Mono", D + "DejaVuSansMono.ttf"))
pdfmetrics.registerFontFamily("Sans", normal="Sans", bold="Sans-Bold")

INK, MUTED, ACCENT = colors.HexColor("#1f2328"), colors.HexColor("#59636e"), colors.HexColor("#8a5a12")
LINE, CODEBG, HEADBG, NOTEBG = (colors.HexColor(c) for c in ("#d8dee4", "#f4f1ea", "#efe7d6", "#fbf6ea"))

s_title = ParagraphStyle("t", fontName="Sans-Bold", fontSize=18.5, leading=23, textColor=INK, spaceAfter=4)
s_sub = ParagraphStyle("s", fontName="Sans", fontSize=10.5, leading=15, textColor=MUTED, spaceAfter=10)
s_h1 = ParagraphStyle("h1", fontName="Sans-Bold", fontSize=13.5, leading=18, textColor=ACCENT, spaceBefore=12,
                      spaceAfter=6, keepWithNext=1)
s_h2 = ParagraphStyle("h2", fontName="Sans-Bold", fontSize=10.5, leading=14, textColor=INK, spaceBefore=8,
                      spaceAfter=4, keepWithNext=1)
s_p = ParagraphStyle("p", fontName="Sans", fontSize=9.5, leading=14, textColor=INK, spaceAfter=5)
s_li = ParagraphStyle("li", parent=s_p, leftIndent=12, bulletIndent=2, spaceAfter=3)
s_cell = ParagraphStyle("c", fontName="Sans", fontSize=8.6, leading=11.5, textColor=INK)
s_cellb = ParagraphStyle("cb", parent=s_cell, fontName="Sans-Bold")
s_code = ParagraphStyle("code", fontName="Mono", fontSize=8.1, leading=11.2, textColor=INK)
s_toc = ParagraphStyle("toc", fontName="Sans", fontSize=9.5, leading=15, textColor=INK, leftIndent=4)
W = A4[0] - 36 * mm
MAX_CODE = 95                      # Preformatted never wraps: longer lines run out of the box
st = []


def C(t): return f"<font name='Mono'>{t}</font>"
def P(t): st.append(Paragraph(t, s_p))
def H1(t): st.extend([CondPageBreak(45 * mm), Paragraph(t, s_h1)])
def H2(t, need=38): st.extend([CondPageBreak(need * mm), Paragraph(t, s_h2)])
def OL(items): st.extend(Paragraph(t, s_li, bulletText=f"{i}.") for i, t in enumerate(items, 1))
def LI(items): st.extend(Paragraph(i, s_li, bulletText="•") for i in items)


def code(text):
    text = text.strip("\n")
    long = [l for l in text.splitlines() if len(l) > MAX_CODE]
    assert not long, f"code line over {MAX_CODE} chars: {long[0]!r}"
    t = Table([[Preformatted(text, s_code)]], colWidths=[W])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), CODEBG), ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                           ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                           ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    st.append(KeepTogether([t, Spacer(1, 6)]))


def note(text):
    t = Table([[Paragraph(text, s_p)]], colWidths=[W])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), NOTEBG), ("LINEBEFORE", (0, 0), (0, -1), 2.5, ACCENT),
                           ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                           ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    st.append(KeepTogether([t, Spacer(1, 8)]))


def shot(name, caption, width=1.0):
    """A screenshot from docs/screenshots/ (made-up accounts from the test fixtures), with a caption."""
    path = os.path.join(SHOTS, name + ".png")
    from reportlab.lib.utils import ImageReader
    iw, ih = ImageReader(path).getSize()
    w = W * width
    img = Image(path, width=w, height=w * ih / iw)
    frame = Table([[img]], colWidths=[w])
    frame.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, LINE), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    cap = Paragraph(caption, ParagraphStyle("cap", parent=s_cell, textColor=MUTED, spaceBefore=3))
    st.append(KeepTogether([frame, cap, Spacer(1, 8)]))


def table(rows, widths, keep=False):
    data = [[Paragraph(c, s_cellb if r == 0 else s_cell) for c in row] for r, row in enumerate(rows)]
    t = Table(data, colWidths=[W * w for w in widths], repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), HEADBG), ("GRID", (0, 0), (-1, -1), 0.4, LINE),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                           ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    st.extend([KeepTogether([t, Spacer(1, 8)])] if keep else [t, Spacer(1, 8)])


def footer(c, doc):
    c.saveState()
    c.setFont("Sans", 7.5)
    c.setFillColor(MUTED)
    c.drawString(18 * mm, 10 * mm, FOOTER)
    c.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Halaman {doc.page}")
    c.setStrokeColor(LINE)
    c.line(18 * mm, 14 * mm, A4[0] - 18 * mm, 14 * mm)
    c.restoreState()


class Doc(SimpleDocTemplate):
    def afterFlowable(self, flowable):                # every H1 goes into the table of contents
        if isinstance(flowable, Paragraph) and flowable.style.name == "h1":
            self.notify("TOCEntry", (0, flowable.getPlainText(), self.page))


# ── content ──────────────────────────────────────────────────────────────────
st += [Paragraph("Plugin account-pool untuk Hermes Agent", s_title),
       Paragraph("Panduan lengkap perintah <font name='Mono'>hermes account</font> dan halaman Accounts di Hermes "
                 "Desktop: jalankan beberapa akun dari satu provider, tambah akun dengan email terverifikasi, pantau "
                 "pemakaian, bagi beban sebelum akun habis, mulai jendela 5 jam akun yang menganggur lebih awal, parkir "
                 "akun sementara, lihat bot mana memakai akun apa, sensor email untuk screenshot, dan terima peringatan.", s_sub)]
table([["Versi", "Repo", "Butuh", "Lisensi"],
       [VERSION, REPO, "Hermes Agent ≥ 0.21.6, Linux atau Windows 10/11", "MIT"]], [0.12, 0.46, 0.30, 0.12])
st.append(Paragraph("Daftar isi", s_h2))
toc = TableOfContents()
toc.levelStyles = [s_toc]
toc.dotsMinLevel = 0
st += [toc, PageBreak()]

H1("1. Ringkasan")
P("Hermes sudah menyimpan beberapa akun per provider dalam satu <b>credential pool</b>, dan memindahkan sesi ke "
  "akun berikutnya saat akun yang dipakai kena limit. Plugin ini menambahkan semua yang belum ada:")
table([
    ["Kebutuhan", "Hermes biasa", "Dengan plugin"],
    ["Menambah akun", C("hermes auth add") + ", tanpa cek akun mana yang sebenarnya login",
     C("add") + " mengecek email asli, membuang login yang salah akun atau duplikat"],
    ["Melihat seberapa penuh tiap akun", "Tidak ada", C("usage") + ", live, termasuk akun yang diparkir"],
    ["Sesi tidak macet di akun yang hampir penuh", "Sesi menunggu sampai 600 detik saat 429, baru pindah",
     C("balance") + " menaruh akun paling longgar di depan dan mengistirahatkan akun ≥ 90%"],
    ["Mengeluarkan akun beberapa jam", "Hapus akun, login lagi nanti", C("park --until 17:00") + ": Hermes tetap menyimpan login dan melewati akun itu sampai jam tersebut"],
    ["Menyisakan akun di jam yang sama tiap minggu", "Tidak bisa", C("schedule &lt;akun&gt; --every \"mon-fri 09:00-17:00\"")],
    ["Tahu bot mana memakai akun apa", "Tidak ada", C("who")],
    ["Tahu token tiap bot dan nilainya di harga API", "Tidak ada", C("report") + ": token per akun, bot, dan model dengan "
     "harga API, plus beban per jam 7 hari terakhir"],
    ["Tahu ada login mati atau pool penuh", "Tidak dilaporkan", "Peringatan desktop dan Telegram, plus ringkasan harian opsional"],
    ["Akun macet setelah refresh token gagal saat jaringan putus", "Menunggu cooldown",
     "Dicoba ulang otomatis tiap 5 menit"],
    ["Jendela 5 jam akun yang menganggur reset lebih cepat", "Jendela baru mulai saat request pertama akun itu",
     C("wake") + " memulainya sekarang; " + C("wake auto-on") + " menjaga semua jendela tetap berjalan"],
    ["Screenshot atau berbagi layar tanpa email akun", "Tidak bisa",
     C("privacy on") + ", atau tombol mata di halaman: " + C("al•••e@e•••.com")],
    ["Melihat semuanya di satu tempat", "Tidak ada", "Halaman Accounts di Hermes Desktop (bagian 8)"],
], [0.28, 0.32, 0.40])
P("Plugin mengubah pool hanya lewat Hermes: API " + C("CredentialPool") + " miliknya dan " + C("hermes auth add")
  + " / " + C("hermes auth remove") + ". Plugin tidak pernah menyimpan login sendiri: semua token tetap di "
  + C("auth.json") + " milik Hermes, dan Hermes yang me-refresh-nya. Plugin tidak memakai token "
  "AI, kecuali untuk " + C("wake") + " yang Anda jalankan atau nyalakan sendiri: satu request kecil per wake (bagian 7.16).")
P("Semua perintah memakai pola yang sama, <b>provider dulu, baru aksi</b>:")
code("hermes account <provider> <action> [target] [options]")

H1("2. Mulai cepat")
code("""
git clone https://github.com/roqianjas/hermes-account-pool.git
cd hermes-account-pool
./install.sh --set-strategy     # plugin, semua profil, timer 5 menit, fill_first

hermes account anthropic add alice@example.com   # satu login per akun, terverifikasi
hermes account anthropic add bob@example.com
hermes account anthropic doctor                  # semua OK?
hermes account anthropic usage                   # pemakaian live per akun
""")
P("Di Windows, di PowerShell (tanpa WSL; penjelasan lengkap di bagian 4.6):")
code("""
git clone https://github.com/roqianjas/hermes-account-pool.git
cd hermes-account-pool
powershell -ExecutionPolicy Bypass -File .\\install.ps1 -SetStrategy

hermes account anthropic add alice@example.com
hermes account anthropic doctor
""")
P("Tanpa salinan git, " + C("hermes plugins install") + " melakukan hal yang sama dengan dua perintah, di Linux "
  "maupun Windows (bagian 4.2). "
  "Setelah itu timer menjaga urutan pool secara otomatis. Sehari-hari yang paling sering dipakai: " + C("usage")
  + ", " + C("who") + ", " + C("park") + ", dan " + C("doctor") + ". Di Hermes Desktop, restart aplikasinya sekali "
  "lalu nyalakan halamannya di Capabilities &gt; Plugins untuk mendapat semua itu dalam satu halaman (bagian 8).")

H1("3. Persyaratan")
LI(["Hermes Agent ≥ 0.21.6 di Linux, atau di Windows 10/11 (instalasi Windows milik Hermes sendiri, tanpa WSL). "
    "Timer memakai systemd user service di Linux (" + C("systemctl --user") + ") dan Task Scheduler di Windows, "
    "tanpa hak admin. Di macOS perintahnya jalan; jalankan " + C("hermes account all balance") + " lewat launchd "
    "atau cron sebagai ganti timer.",
    "Dua akun atau lebih dari provider yang sama. Dukungan pemakaian bawaan: Claude Pro / Max / Team ("
    + C("anthropic") + ") dan ChatGPT Plus / Pro / Team (" + C("openai-codex") + "). Provider lain mendapat "
    "perintah umum (bagian 12).",
    "Opsional: notifikasi desktop butuh " + C("notify-send") + " di Linux (paket " + C("libnotify-bin")
    + "); di Windows notifikasi muncul sebagai notifikasi Windows lewat Windows PowerShell, yang ada di setiap "
    "Windows 10 dan 11. Peringatan Telegram butuh bot "
    "Telegram yang sudah diatur di Hermes, dengan home channel (kirim " + C("/sethome") + " ke bot di chat yang "
    "harus menerima peringatan) atau id chat yang diberikan lewat " + C("notify telegram-to=") + ".",
    "Opsional: Hermes Desktop dengan dukungan desktop plugin, untuk halaman Accounts. Diuji dengan Hermes Agent 0.21.6."])

H1("4. Instalasi, update, uninstall")
P("Instalasi plugin memasang plugin ke satu profil. Proyek ini butuh sedikit lebih: pelacak sesinya di setiap profil "
  "(supaya " + C("who") + " melihat semua bot), " + C("account-pool") + " tercantum di setiap profil (supaya Hermes "
  "Desktop bisa menampilkan halamannya profil mana pun yang dijalankan), dan timer jika Anda mau. Bagian itu "
  "dikerjakan " + C("hermes account &lt;provider&gt; setup") + ", setelah cara instalasi mana pun.")
H2("4.1 Instalasi dari git")
code("""
git clone https://github.com/roqianjas/hermes-account-pool.git
cd hermes-account-pool
./install.sh --set-strategy
""")
P(C("install.sh") + " menyalin " + C("account-pool") + " (beserta halaman Hermes Desktop dan pelacak sesi) ke "
  + C("$HERMES_HOME/plugins/") + " (biasanya " + C("~/.hermes/plugins/")
  + "), mengaktifkannya di profil default, menjalankan "
  + C("hermes account &lt;provider&gt; setup --yes --timer") + " untuk tiap provider (ditambah " + C("--strategy")
  + " jika " + C("--set-strategy") + "), lalu " + C("doctor") + ". Pada update dari 3.x, " + C("setup") + " juga "
  "menghapus plugin terpisah " + C("account-pool-tracker") + ", setelah " + C("install.sh") + " mencadangkannya.")
table([
    ["Opsi", "Fungsi"],
    [C("--provider &lt;nama&gt;"), "Provider yang dijalankan " + C("setup") + "-nya (default " + C("anthropic")
     + "); ulangi untuk beberapa provider. Berpengaruh pada " + C("--set-strategy") + ", yang mengatur "
     + C("fill_first") + " untuk tiap provider itu. Timer menyeimbangkan semua provider yang punya akun, provider "
     "mana pun yang Anda sebut."],
    [C("--set-strategy"), "Atur " + C("fill_first") + " untuk tiap provider di semua profil. Tanpa opsi ini strategi "
     "tidak disentuh, dan " + C("doctor") + " memberi tahu jika salah."],
    [C("--no-timer"), "Tanpa timer. " + C("balance") + " dijalankan sendiri."],
    [C("-h") + ", " + C("--help"), "Tampilkan opsi."],
], [0.26, 0.74])
H2("4.2 Instalasi dengan hermes plugins install")
P("Folder yang sama, langsung dari repo ini, tanpa salinan git:")
code("""
hermes plugins install roqianjas/hermes-account-pool#plugins/account-pool --enable
hermes account anthropic setup --timer --strategy
""")
P("Jalankan di profil default (tanpa " + C("-p") + "): perintahnya ada di sana, dan " + C("setup") + " menautkan "
  "plugin dari sana ke profil lain, supaya pelacak sesinya jalan di setiap profil.")
P("Hermes memindai plugin dari GitHub sebelum memasangnya, dan berhenti bila ada temuan. Untuk "
  + C("account-pool") + " ada 16 temuan, semuanya memang bagian dari cara kerja plugin:")
LI(["15 panggilan " + C("subprocess") + ": " + C("notify-send") + " (notifikasi desktop di Linux), "
    + C("hermes send") + " (peringatan Telegram), " + C("systemctl --user") + " lima kali (status timer untuk "
    + C("doctor") + " dan halaman, " + C("setup --timer") + " di Linux), " + C("schtasks") + " dan Windows "
    "PowerShell di " + C("winsys.py") + " (timer dan notifikasi desktop di Windows), " + C("hermes config set")
    + " (cadangan untuk " + C("strategy") + " dan " + C("setup") + " bila penulis config Hermes tidak bisa diimpor), "
    + C("hermes auth add") + " dua kali (" + C("add") + " dan " + C("relogin") + " di terminal; <b>Add account</b> "
    "dan <b>Sign in again</b> di halaman, di " + C("signin.py") + "), " + C("taskkill") + " (menghentikan login "
    "halaman yang dibatalkan di Windows), " + C("hermes auth remove") + " (" + C("remove") + "), dan "
    + C("hermes plugins remove account-pool-tracker") + " (" + C("setup") + ", sekali, saat update dari 3.x).",
    "1 pembacaan " + C("/proc/self/cgroup") + ", untuk tahu apakah proses ini service timer (hanya Linux)."])
P("Semuanya tercantum di bagian pengungkapan keamanan (bagian 13). Di terminal, Hermes menampilkan temuan itu "
  "lalu bertanya " + C("Install anyway? ... [y/N]") + ": baca temuannya, lalu jawab " + C("y") + ". Tanpa terminal "
  "(skrip, shell milik agen) Hermes langsung berhenti; tambahkan " + C("--force") + " di sana. "
  + C("hermes plugins update") + " memasang versi baru tanpa bertanya lagi, dan " + C("install.sh")
  + " menyalin folder sendiri, jadi keduanya tidak dihentikan pemindaian.")
H2("Katalog plugin Hermes")
P("Katalog plugin Hermes hanya memuat plugin yang tidak pernah memegang login sendiri: token OAuth dan API key "
  "tetap di Hermes (aturan katalog 11). Sampai 3.13, " + C("account-pool") + " menyimpan login akun parkir di file "
  "sendiri dan menjalankan login dengan kodenya sendiri, jadi hanya bisa dipasang dari repo ini. Versi 4.0 "
  "menyerahkan semua itu ke Hermes dan sudah diajukan ke katalog:")
table([
    ["Fitur", "Cara kerjanya sejak 4.0"],
    [C("park") + ", " + C("unpark") + " dan jadwal", "Akun tetap di pool Hermes. Plugin meminta pool Hermes "
     "melewatinya sampai waktu reset (" + C("mark_exhausted_and_rotate") + ", alasan " + C("parked") + ") dan "
     "mengembalikannya (" + C("reset_status") + "). Daftar parkir milik plugin hanya berisi label, id, dan waktu, "
     "tanpa token."],
    [C("usage") + ", " + C("balance") + ", " + C("check") + ", cek email setelah login",
     "Plugin mengirim access token akun, seperti yang disimpan Hermes, ke endpoint usage dan profil milik provider. "
     "Token yang kedaluwarsa di-refresh oleh Hermes (" + C("try_refresh_matching") + "), yang menyimpan pasangan "
     "baru di pool-nya."],
    ["<b>Add account</b> dan <b>Sign in again</b> di halaman Accounts",
     "Backend halaman menjalankan " + C("hermes auth add") + " milik Hermes dan menampilkan link serta "
     "pertanyaannya. Hermes yang login dan menyimpan akun; plugin tidak pernah melihat code verifier atau token."],
    ["Peringatan Telegram", "Dikirim dengan " + C("hermes send -t telegram") + " ke home channel bot, atau ke chat "
     "yang Anda sebut. Plugin tidak membaca " + C(".env") + "."],
    ["Akun di setiap profil", "Dibaca lewat " + C("read_credential_pool") + " milik Hermes, tidak langsung dari "
     + C("auth.json") + "."],
    ["Pelacak sesi", "Bagian dari " + C("account-pool") + " (hook " + C("post_api_request") + "), bukan plugin kedua "
     "lagi."],
], [0.30, 0.70])
P("Yang masih dilakukan plugin dengan token tercantum di bagian pengungkapan keamanan (bagian 13). Selama "
  "katalog belum memuatnya, pasang dari repo ini seperti di atas.")
H2("4.3 Yang dikerjakan setup", need=70)
code("""
$ hermes account anthropic setup --timer
[anthropic] Setup: the default profile and 2 other profile(s) in /home/you/.hermes
  Accounts page    backend listed in 0 of 2 other profile(s)
  Session tracking 4.0.1, active in 1 of 3 profile(s)
  Balance timer    not installed
  Rotation         fill_first in all 3 profile(s)
Changes:
  - list account-pool in plugins.enabled of worker-1 (Hermes Desktop serves the page's ...)
  - list account-pool in plugins.enabled of worker-2 (...)
  - link account-pool into worker-1 (/home/you/.hermes/profiles/worker-1/plugins/account-pool
    -> /home/you/.hermes/plugins/account-pool), so its session tracking runs there
  - link account-pool into worker-2 (...)
  - install the balance timer: systemd user units in /home/you/.config/systemd/user, every
    5 minutes runs hermes account all balance (every provider with accounts, now: anthropic;
    providers you add later are included by themselves)
Apply these changes? [y/N]
""")
P("Di Windows, baris timer berbunyi " + C("install the balance timer: a Task Scheduler task \"Hermes Account "
  "Balance\" (C:\\Users\\you\\AppData\\Local\\hermes\\account-pool-timer), every 5 minutes runs ...") + ".")
P(C("setup") + " menampilkan keadaan sekarang dan setiap perubahan yang akan dibuat, bertanya sekali, lalu "
  "mengerjakannya satu per satu; setiap perubahan dicatat di log aktivitas (bagian 7.14). Jalankan lagi dan "
  "hasilnya " + C("Nothing to change") + ".")
table([
    ["Bagian", "Yang diubah"],
    ["Halaman Accounts", "Menambahkan " + C("account-pool") + " ke " + C("plugins.enabled") + " setiap profil di "
     + C("$HERMES_HOME/profiles/") + " (alasannya di bagian 8.2). Profil itu tidak mendapat perintah atau tool apa "
     "pun. Profil yang mencantumkan " + C("account-pool") + " di " + C("plugins.disabled") + " dilewati dan disebut."],
    ["Pelacak sesi", "Menautkan " + C("plugins/account-pool") + " setiap profil lain ke salinan profil default "
     "(profil hanya memuat plugin dari folder " + C("plugins/") + " miliknya). Di sana plugin hanya mendaftarkan "
     "pelacak sesinya, hook " + C("post_api_request") + ": tanpa perintah, tanpa tool. Satu salinan berarti satu "
     "update untuk semua profil. Profil yang mencantumkan " + C("account-pool") + " di " + C("plugins.disabled")
     + " dibiarkan."],
    ["Plugin sebelum 4.0", "Menghapus plugin terpisah " + C("account-pool-tracker") + ": symlink dan entri "
     + C("plugins.enabled") + "-nya di profil lain, lalu plugin itu sendiri di profil default dengan "
     + C("hermes plugins remove account-pool-tracker") + ". Kalau dibiarkan, setiap panggilan API terhitung dua kali."],
    [C("--timer"), "Linux: menulis " + C("hermes-account-balance.service") + " dan " + C(".timer") + " ke "
     + C("~/.config/systemd/user/") + ", menyalakan timer, dan menjalankan putaran pertama di latar belakang. "
     "Windows: menulis " + C("balance.cmd") + " dan " + C("balance.vbs") + " ke "
     + C("%LOCALAPPDATA%\\hermes\\account-pool-timer\\") + ", mendaftarkan task Task Scheduler <b>Hermes Account "
     "Balance</b> untuk user Anda (tiap 5 menit, tanpa hak admin, tanpa jendela), lalu menjalankan putaran pertama. "
     "Service menjalankan " + C("hermes account all balance") + " tiap 5 menit: semua provider yang punya akun, "
     "jadi provider yang baru mendapat akun pertamanya nanti (misalnya Codex) ikut diseimbangkan mulai putaran "
     "berikutnya, tanpa " + C("setup") + " kedua. Unit dari 3.10.2 atau lebih lama berisi satu baris per provider; "
     + C("setup --timer") + " untuk provider yang belum ada di sana mengubahnya ke " + C("all") + ". "
     + C("HERMES_HOME") + " kustom ditulis ke service. Opsi yang Anda tambahkan sendiri (" + C("--threshold 85")
     + ") dan interval yang diubah tetap dipertahankan."],
    [C("--strategy"), "Mengatur " + C("credential_pool_strategies.&lt;provider&gt;: fill_first") + " di profil yang "
     "nilainya lain. " + C("balance") + " membutuhkannya (bagian 5)."],
    [C("--undo"), "Menghapus symlink plugin dan entri " + C("plugins.enabled") + " di profil lain, serta "
     "mengeluarkan provider itu dari timer: timer lalu menjalankan provider lain yang punya akun, satu baris per "
     "provider, dan tidak lagi mengambil provider baru; timer hilang jika tidak ada provider tersisa. Plugin di profil "
     "default, akun, akun parkir, pengaturan, file data, dan strategi tetap. Akun parkir yang akan tetap di luar "
     "rotasi disebut namanya."],
    [C("--yes"), "Tanpa pertanyaan. Tanpa terminal (cron, shell milik agent), " + C("setup") + " hanya menampilkan "
     "rencananya dan tidak mengubah apa pun kecuali dengan " + C("--yes") + "."],
], [0.22, 0.78])
P("Semua perubahan config lewat penulis config milik Hermes (" + C("hermes config set") + "), jadi format "
  "dan pengecekan file tetap milik Hermes. Tanpa systemd atau Task Scheduler (macOS), " + C("--timer")
  + " memberi tahu; jalankan " + C("balance") + " dengan cara lain (launchd, cron).")
P(C("HERMES_HOME") + " kustom dihormati. Sesi yang sedang berjalan baru memuat pelacak sesi setelah " + C("/reset")
  + ", atau setelah gateway/desktop di-restart. Halaman Accounts butuh dua langkah lagi di Hermes Desktop (bagian "
  "8.1). Setelah update, " + C("doctor") + " dan halaman Accounts menyebut proses yang masih memakai pelacak lama. "
  "Proses yang masih memuat " + C("account-pool-tracker") + " dari 3.x tetap menghitung dengannya sampai restart; "
  "pelacak baru menyingkir, jadi tidak ada panggilan yang terhitung dua kali. "
  "Profil yang dibuat belakangan perlu " + C("setup") + " lagi supaya halaman tetap jalan saat Desktop memakai "
  "profil itu; " + C("doctor") + " menyebut profil seperti ini. Cek hasilnya:")
code("""
hermes account anthropic doctor
systemctl --user list-timers hermes-account-balance.timer      # Linux
schtasks /Query /TN "Hermes Account Balance"                   # Windows
""")
H2("4.4 Update")
P("Instalasi dengan " + C("hermes plugins install") + ":")
code("""
hermes plugins update account-pool
hermes account anthropic setup        # biasanya "Nothing to change"
""")
P("Hermes mengganti folder plugin di profil default. Symlink di profil lain menunjuk ke folder itu, jadi "
  "semua profil mendapat versi baru dengan satu update. Dari 3.x, baca bagian 4.7 dulu. Instalasi dari git:")
code("""
cd hermes-account-pool
git pull
./install.sh                # pakai opsi --set-strategy / --provider yang sama seperti dulu
""")
P("Di Windows: " + C("git pull") + ", lalu " + C("powershell -ExecutionPolicy Bypass -File .\\install.ps1")
  + " dengan opsi yang sama seperti dulu.")
P("Folder plugin lama dicadangkan ke " + C("$HERMES_HOME/plugin-backups/&lt;nama&gt;.&lt;waktu&gt;") + " (di luar "
  + C("plugins/") + ", jadi tidak pernah dimuat dua kali). Akun, akun parkir, riwayat, dan pengaturan tetap. Tanpa "
  + C("--set-strategy") + ", strategi tidak diubah. Restart Hermes Desktop setelah update apa pun supaya halaman "
  "dan backend-nya yang baru ikut dimuat.")
H2("4.5 Uninstall")
P("Unpark dulu akun yang diparkir jika ingin akun itu kembali ke rotasi. Akun parkir tetap ada di pool Hermes, "
  "tetapi Hermes melewatinya sampai waktu parkirnya habis: jam " + C("--until") + ", atau sampai 30 hari untuk "
  "parkir tanpa jam. Tanpa plugin, " + C("hermes auth reset &lt;provider&gt;") + " mengembalikan semua akun "
  "provider itu yang ditahan sekaligus. Instalasi dengan " + C("hermes plugins install") + ":")
code("""
hermes account anthropic setup --undo     # symlink plugin, entri halaman, timer
hermes plugins remove account-pool
""")
P("Instalasi dari git:")
code("""
./uninstall.sh                                                  # Linux
powershell -ExecutionPolicy Bypass -File .\\uninstall.ps1        # Windows
""")
P("Timer, plugin (termasuk halaman Accounts), symlink-nya di profil lain, entri " + C("account-pool") + " di "
  + C("plugins.enabled") + " tiap profil, dan sisa " + C("account-pool-tracker") + " dari 3.x dihapus. Akun di credential pool <b>tidak</b> disentuh. Akun yang "
  "diparkir <b>tidak</b> dikembalikan ke rotasi: skrip memperingatkan dan meminta konfirmasi. File data dan "
  + C("credential_pool_strategies") + " tetap; skrip menampilkan daftar file yang bisa dihapus manual.")

H2("4.6 Windows", need=80)
P("Hermes berjalan langsung di Windows, begitu juga plugin ini: tidak perlu WSL. Di PowerShell, sebagai user "
  "Anda sendiri (tanpa hak admin):")
code("""
git clone https://github.com/roqianjas/hermes-account-pool.git
cd hermes-account-pool
powershell -ExecutionPolicy Bypass -File .\\install.ps1 -SetStrategy
""")
P(C("install.ps1") + " mengerjakan yang sama dengan " + C("install.sh") + ": menyalin plugin ke "
  + C("%LOCALAPPDATA%\\hermes\\plugins\\") + " (atau " + C("$env:HERMES_HOME\\plugins\\") + "), mengaktifkan "
  + C("account-pool") + ", menjalankan " + C("hermes account &lt;provider&gt; setup --yes --timer") + ", lalu "
  + C("doctor") + ". " + C("-ExecutionPolicy Bypass") + " hanya berlaku untuk sekali jalan itu; perlu karena "
  "Windows memblokir skrip unduhan secara default.")
table([
    ["Opsi", "Fungsi"],
    [C("-Provider anthropic,openai-codex"), "Provider yang dijalankan " + C("setup") + "-nya (default "
     + C("anthropic") + ")"],
    [C("-SetStrategy"), "Atur " + C("fill_first") + " untuk tiap provider di semua profil"],
    [C("-NoTimer"), "Tanpa task Task Scheduler"],
], [0.36, 0.64])
P("Tanpa git, pakai " + C("hermes plugins install") + " (bagian 4.2); caranya sama di Windows. Yang berbeda di Windows:")
table([
    ["", "Linux", "Windows"],
    ["Timer", "unit systemd user di " + C("~/.config/systemd/user/"), "task Task Scheduler <b>Hermes Account "
     "Balance</b>, filenya di " + C("%LOCALAPPDATA%\\hermes\\account-pool-timer\\")],
    ["Log timer", C("journalctl --user -u hermes-account-balance.service"), C("account-pool-timer\\balance.log")
     + " (dijaga di bawah 1 MB)"],
    ["Kapan timer jalan", "selalu, juga sebelum login", "selama Anda login ke Windows; putaran yang terlewat "
     "dikejar saat Anda login"],
    ["Notifikasi desktop", C("notify-send"), "notifikasi Windows (tampil atas nama Windows PowerShell)"],
    ["Plugin di profil lain", "symlink", "symlink, atau directory junction jika Windows tidak mengizinkan "
     "symlink (tanpa Developer Mode)"],
    ["Uninstall dari git", C("./uninstall.sh"), C("powershell -ExecutionPolicy Bypass -File .\\uninstall.ps1")],
], [0.20, 0.34, 0.46])
P("Selebihnya sama: semua perintah dan halaman Accounts. Cara mengelola task-nya ada di bagian 11.")

H2("4.7 Update dari 3.x", need=90)
P("4.0 mengubah tempat akun parkir disimpan dan menggabungkan pelacak sesi ke " + C("account-pool") + ". Update "
  "plugin seperti biasa (" + C("hermes plugins update account-pool") + ", atau " + C("git pull") + " dan "
  + C("./install.sh") + "), lalu jalankan " + C("setup") + " sekali:")
code("""
hermes plugins update account-pool
hermes account anthropic setup --timer    # tautkan plugin ke semua profil, hapus tracker lama
hermes account anthropic doctor
""")
code("""
[anthropic] Setup: the default profile and 2 other profile(s) in /home/you/.hermes
  Accounts page    backend listed in 2 of 2 other profile(s)
  Session tracking 4.0.1, active in 1 of 3 profile(s)
  Balance timer    runs every provider with accounts (now: anthropic), active
  Rotation         fill_first in all 3 profile(s)
Changes:
  - link account-pool into worker-1 (/home/you/.hermes/profiles/worker-1/plugins/account-pool
    -> /home/you/.hermes/plugins/account-pool), so its session tracking runs there
  - link account-pool into worker-2 (...)
  - remove the retired account-pool-tracker from worker-1 (its link and plugins.enabled entry)
  - remove the retired account-pool-tracker from worker-2 (its link and plugins.enabled entry)
  - remove the retired account-pool-tracker plugin from the default profile (hermes plugins
    remove account-pool-tracker): account-pool counts sessions itself now
Apply these changes? [y/N] y
""")
P("Yang terjadi pada data Anda:")
LI(["<b>Akun parkir.</b> Perintah " + C("hermes account") + " pertama setelah update (atau putaran timer "
    "berikutnya) memindahkan setiap akun dari " + C("account-pool-parked.json") + " kembali ke pool Hermes, ditahan "
    "di luar rotasi seperti " + C("park") + " sekarang, dengan jam " + C("--until") + " yang sama, lalu menghapus "
    "file lama itu. Parkir yang waktunya sudah lewat kembali ke rotasi. Log aktivitas mendapat satu baris per "
    "provider. Bila ada yang gagal, file lama tetap ada dan putaran berikutnya mencoba lagi, jadi tidak ada login "
    "yang hilang. " + C("list") + " menampilkan akun parkir yang sama sebelum dan sesudahnya.",
    "<b>Token, sesi, dan riwayat.</b> " + C("account-pool-tokens.json") + ", " + C("account-pool-sessions.json")
    + " dan riwayat tetap dengan format yang sama; penghitungan berlanjut dari titik pelacak lama berhenti.",
    "<b>Bot yang sedang jalan.</b> Gateway, Hermes Desktop, atau sesi panjang yang dimulai sebelum update masih "
    "memuat pelacak lama dan tetap menghitung dengannya sampai restart; pelacak baru menyingkir, jadi tidak ada "
    "yang terhitung dua kali. " + C("doctor") + " menyebut proses itu.",
    "<b>Peringatan Telegram.</b> 3.x mengirimnya ke user pertama di " + C("TELEGRAM_ALLOWED_USERS") + ". 4.0 "
    "mengirimnya ke home channel bot. Bila bot belum punya, kirim " + C("/sethome") + " ke bot di chat yang harus "
    "menerima peringatan, atau sebut chat-nya: " + C("hermes account anthropic notify telegram-to=&lt;id chat&gt;")
    + ". " + C("doctor") + ", " + C("notify") + " dan tab Alerts memberi tahu selama home channel belum ada.",
    "<b>Versi Hermes.</b> 4.0 butuh Hermes Agent 0.21.6 atau lebih baru."])

H1("5. Konsep dasar")
H2("Credential pool dan strategi rotasi")
P("Hermes menyimpan akun tiap provider dalam satu daftar di " + C("~/.hermes/auth.json") + ", dipakai bersama "
  "semua profil. Pengecualian: profil yang pernah menjalankan " + C("hermes -p &lt;profil&gt; auth add") + " punya "
  "pool sendiri (" + C("doctor") + " memperingatkannya).")
P("Akun mana yang diambil sesi baru adalah pengaturan Hermes, per profil dan provider: "
  + C("credential_pool_strategies.&lt;provider&gt;") + ". Pengaturan ini milik Hermes. Plugin menampilkannya ("
  + C("strategy") + ", header halaman Accounts), " + C("doctor") + " memeriksanya, dan plugin hanya mengubahnya "
  "jika Anda minta: lewat " + C("strategy") + " (7.10) atau dari halaman. Keduanya menulis lewat "
  + C("hermes config set") + " milik Hermes sendiri.")
table([
    ["Strategi", "Sesi baru mengambil", "Dengan plugin ini"],
    [C("fill_first") + " (bawaan Hermes)", "Akun pertama yang bisa dipakai di daftar",
     "<b>Pakai ini.</b> " + C("balance") + " menaruh akun dengan sisa kuota terbanyak di urutan pertama, jadi setiap sesi "
     "baru mulai di sana."],
    [C("round_robin"), "Akun berikutnya secara bergiliran; akun itu lalu dipindah ke urutan terakhir",
     "Bentrok dengan " + C("balance") + ": keduanya menulis urutan, dan giliran tidak melihat sisa kuota."],
    [C("least_used"), "Akun yang paling jarang dipilih komputer ini",
     "Menghitung jumlah pemilihan, bukan kuota: pemakaian di claude.ai atau Claude Code tidak terlihat."],
    [C("random"), "Akun acak yang bisa dipakai", "Urutan dari " + C("balance") + " diabaikan."],
], [0.17, 0.33, 0.50])
P(C("fill_first") + " ditambah timer balance adalah rotasi berdasarkan kuota: posisi teratas berpindah ke akun yang "
  "paling longgar setiap 5 menit. " + C("hermes account &lt;provider&gt; strategy fill_first") + " dan "
  + C("setup --strategy") + " (atau " + C("install.sh --set-strategy") + ") memasang " + C("fill_first") + " di semua profil.")
H2("Sesi yang berjalan tetap di akunnya")
P("Urutan menentukan tempat <b>sesi baru</b> mulai. Sesi yang sedang berjalan tetap di akunnya sampai akun itu kena "
  "limit; setelah itu Hermes memindahkannya ke akun berikutnya yang bisa dipakai, yang dijaga " + C("balance")
  + " tetap paling longgar. Akibatnya akun yang sedang dipakai turun ke tengah daftar seiring pemakaiannya naik, dan akun "
  "teratas biasanya kosong karena sedang menunggu sesi berikutnya. Sesi memilih akun lagi setelah " + C("/reset")
  + ", di chat baru, atau setelah gateway atau Hermes Desktop di-restart. Memindahkan sesi lebih awal akan membuang "
  "prompt cache-nya, dan mengirim ulang konteks yang panjang memakan kuota lebih banyak daripada yang dihemat.")
H2("Status akun")
table([
    ["Status", "Diatur oleh", "Dipakai?", "Berakhir saat"],
    [C("active") + " / " + C("ok"), "", "Ya", ""],
    [C("BENCHED"), C("balance") + ", saat ≥ ambang (90%)", "Tidak", "Jendela pemakaian reset, atau turun di bawah ambang"],
    [C("LIMITED") + " / RATE LIMITED", "Hermes, setelah 429 atau 402 dari provider", "Tidak", "Jam reset dari provider (atau 1 jam)"],
    [C("COOLING DOWN"), "Hermes, setelah refresh token gagal (biasanya jaringan)", "Tidak", C("balance") + " mencoba ulang tiap 5 menit"],
    [C("DEAD"), "Hermes, saat provider menolak refresh token", "Tidak", "Anda menjalankan " + C("relogin")],
    [C("PARKED"), "Anda, dengan " + C("park"), "Tidak, login tetap disimpan", C("unpark") + ", atau waktu " + C("--until") + " lewat"],
], [0.20, 0.32, 0.16, 0.32])
H2("Jendela 5 jam")
P("Claude dan ChatGPT membatasi akun per jendela 5 jam. Jendela itu tidak berjalan menurut jam sendiri: ia mulai saat "
  "request pertama akun itu setelah jendela sebelumnya selesai, lalu reset 5 jam kemudian. Akun yang menganggur tidak "
  "punya jendela yang berjalan; halaman menampilkannya sebagai " + C("not started") + " di kolom <b>Resets</b>. "
  + C("wake") + " memulainya dengan satu request kecil, sehingga reset datang lebih cepat (bagian 7.16).")
H2("Park, bench, remove")
P("<b>Park</b> adalah keputusan Anda dan login tetap disimpan. <b>Bench</b> otomatis dan sementara. <b>Remove</b> "
  "menghapus login; untuk memakai akun itu lagi harus login baru.")
H2("Adapter dan profil default")
P("Pemakaian dan email asli butuh API khusus tiap provider. Kodenya ada di satu <b>adapter</b> per provider di "
  + C("providers.py") + ". Tanpa adapter, perintah umum tetap jalan. Perintah " + C("hermes account") + " hanya "
  "dipasang di <b>profil default</b>, jadi bot pekerja tidak bisa menambah, menghapus, atau mengurutkan akun. Akun "
  "yang ditambahkan dari profil default dipakai bersama oleh semua profil.")

H1("6. Menambah dan menghapus akun")
H2("6.1 Menambah akun Claude")
OL(["Siapkan email akun Claude (Pro, Max, atau Team) yang belum ada di pool. Cek dengan "
    + C("hermes account anthropic list") + ".",
    "Buka terminal di profil <b>default</b> (tanpa " + C("-p") + "), lalu jalankan "
    + C("hermes account anthropic add name@example.com") + ".",
    "Jawab " + C("y") + ". Hermes menampilkan link login.",
    "Buka link itu di browser yang login sebagai <b>akun tersebut</b>: profil Chrome milik akun itu, atau jendela "
    "<b>private / incognito</b> lalu login. Pastikan halaman menulis " + C("Logged in as name@example.com")
    + "; jika bukan, klik <b>Switch account</b>. Browser yang login sebagai akun lain akan memberikan akun lain itu ke Hermes.",
    "Jika muncul <b>\"Sign in again to continue\"</b>, itu normal: Anthropic meminta login ulang bila login di browser "
    "sudah lama. Klik, lalu login sebagai akun yang sama. " + C("hermes auth add") + " bawaan pun mendapat halaman yang sama.",
    "Setujui akses (Authorize), salin kode yang muncul, tempel ke terminal, lalu Enter.",
    "Pastikan muncul " + C("Verified") + " dan " + C("Added") + ". Akun langsung diurutkan.",
    "Cek hasilnya: " + C("hermes account anthropic check") + " (email asli) dan "
    + C("hermes account anthropic usage") + "."])
code("""
$ hermes account anthropic add name@example.com
Add name@example.com to anthropic
  1. Open the sign-in link in a browser that is signed in as THIS account:
     its own Chrome profile, or a private / incognito window.
  2. Make sure the page says: Logged in as name@example.com  (otherwise: Switch account)
     "Sign in again to continue" is normal when that browser login is old.
  3. Authorize, then paste the code back here.
  The account is kept only if the sign-in really is that account and not a duplicate.
Continue? [y/N] y
   (login Hermes: buka link, login, salin kode, tempel)
Verified: name@example.com
Added name@example.com (id=4f1c2a) to anthropic.
""")
P("Kemungkinan hasil " + C("add") + ":")
table([["Kondisi", "Pesan", "Pool"],
       ["Login benar", C("Verified ... Added ..."), "Akun masuk dan langsung diurutkan"],
       ["Browser login ke akun lain", C("Signed in as X, not name@example.com. The sign-in was discarded."), "Tidak berubah"],
       ["Browser login ke akun yang sudah ada", C("X is already in the pool as '...' (id=...). The duplicate sign-in was discarded."), "Tidak berubah"],
       ["Email sudah di rotasi", C("... is already in rotation. To sign it in again: ... relogin ..."), "Tidak berubah (ditolak sebelum login)"],
       ["Email sedang diparkir", C("... is parked. Return it with: ... unpark ..."), "Tidak berubah (ditolak sebelum login)"],
       ["Login gagal", C("Sign-in did not complete. Nothing was added."), "Tidak berubah"],
       ["Anda menekan Ctrl+C", C("Cancelled (Ctrl+C). Nothing was added.") + " (exit code 130)", "Tidak berubah; entri setengah jadi dihapus"]],
      [0.24, 0.50, 0.26])
LI(["Setelah pesan " + C("discarded") + ", pindahkan browser ke akun yang benar (atau jendela private baru), lalu "
    "jalankan " + C("add") + " lagi.",
    "Opsi: " + C("--yes") + " melewati konfirmasi. " + C("--key") + " menambah akun API key: key diminta oleh plugin "
    "tanpa ditampilkan, jadi tidak pernah muncul di command line atau " + C("ps") + "."])
note("Akun baru langsung dipakai semua profil, tetapi sesi bot yang sedang berjalan tetap memakai akunnya sekarang. "
     "Akun baru dipakai mulai sesi berikutnya (atau setelah " + C("/reset") + ").")
H2("6.2 Menghapus akun")
code("""
$ hermes account anthropic remove bob@example.com
Remove bob@example.com (id=9f2a02) from anthropic.
Its login is deleted; to use it again you must sign in again (add).
To take it out of rotation for a while instead: hermes account anthropic park bob@example.com
Delete it? [y/N] y
Removed bob@example.com.
""")
LI(["Target boleh email atau id. Akun yang sedang diparkir juga bisa dihapus langsung.",
    "Ditolak jika itu akun aktif terakhir: " + C("Refused: ... is the last working anthropic account."),
    "Untuk keluar sementara (cuti, limit mingguan), pakai " + C("park") + ", bukan " + C("remove") + ".",
    "Untuk memakainya lagi nanti, tambahkan ulang dengan " + C("add") + " (login baru)."])
H2("6.3 Hal yang perlu dihindari")
LI(["Jangan pakai " + C("hermes -p &lt;profil&gt; auth add") + ": profil itu akan punya pool sendiri dan berhenti "
    "memakai akun bersama. " + C("doctor") + " mendeteksinya.",
    "Jangan pakai " + C("hermes auth add") + " langsung: tidak ada cek email, sehingga label bisa salah dan duplikat bisa masuk.",
    "Jangan menyalin token Hermes ke aplikasi atau perangkat lain. Refresh token sekali pakai, jadi salah satu login "
    "akan mati. Login terpisah ke akun yang sama di aplikasi lain tidak masalah."])
H2("6.4 Akun Codex")
P("Perintahnya sama untuk " + C("openai-codex") + " (ChatGPT Plus, Pro, Business, dan Enterprise). Bedanya di cara "
  "login: secara default lewat browser yang kembali ke komputer ini, jadi tidak ada kode yang perlu ditempel.")
code("""
hermes account openai-codex list
hermes account openai-codex add you@example.com
""")
OL(["Jawab " + C("y") + ". Hermes menampilkan link login di " + C("auth.openai.com") + ".",
    "Buka link itu di browser <b>di komputer ini</b> yang login ChatGPT sebagai <b>akun itu</b>: profil Chrome "
    "sendiri, atau jendela private lalu login di sana.",
    "Pilih workspace jika ChatGPT bertanya, lalu authorize.",
    "Browser membuka " + C("http://localhost:1455/auth/callback?...") + " dan menampilkan <b>OpenAI Codex "
    "authorization received</b>. Halaman itu berasal dari Hermes di komputer Anda: login sudah selesai dan tab boleh "
    "ditutup. Kode di alamatnya hanya berlaku sekali dan sudah terpakai.",
    "Cari " + C("Verified: you@example.com") + " dan " + C("Added ...") + ", lalu cek dengan "
    + C("hermes account openai-codex check") + " dan " + C("usage") + "."])
code("""
$ hermes account openai-codex add you@example.com
Add you@example.com to openai-codex
  1. Open the sign-in link in a browser ON THIS COMPUTER that is signed in to ChatGPT as THIS
     account: its own Chrome profile, or a private / incognito window.
  2. Pick the workspace and authorize. The browser then opens a localhost:1455 page that says
     "authorization received", and the sign-in finishes here by itself.
     Browser on another computer? Use the Accounts page in Hermes Desktop (it takes the
     address the browser ends on), or sign in with a code: add --device.
  The account is kept only if the sign-in really is that account and not a duplicate.
Continue? [y/N] y
   ... Hermes prints the link and waits for the browser ...
Verified: you@example.com
Added you@example.com (id=7c41e0) to openai-codex.
""")
P("<b>Kenapa browser, bukan kode.</b> Workspace ChatGPT Business dan Enterprise mematikan login dengan kode perangkat "
  "kecuali owner menyalakannya, dan OpenAI lalu menjawab <i>\"Please contact your workspace admin to enable device "
  "code authentication\"</i>. Login lewat browser jalan di kedua keadaan. Alurnya sama dengan Codex CLI "
  "(authorization code + PKCE), dijalankan oleh " + C("hermes auth add openai-codex --browser") + " milik Hermes "
  "sendiri.")
P("<b>Kode perangkat</b> (" + C("--device") + "): " + C("hermes account openai-codex add you@example.com --device")
  + " menampilkan kode; buka " + C("https://auth.openai.com/codex/device") + ", masukkan kodenya, lalu konfirmasi. "
  "Berguna bila browser ada di komputer lain dan Anda tidak memakai halaman Accounts. Di workspace Business atau "
  "Enterprise, owner harus lebih dulu menyalakan <i>Permissions &amp; roles &gt; Codex and Work Local &gt; Enable "
  "device code sign-in for Codex</i> (akun pribadi: <i>Settings &gt; Security</i>); pengaturannya bisa butuh waktu "
  "sebelum berlaku.")
P("<b>Codex CLI dan VS Code tidak tersentuh.</b> Hermes membuat login sendiri untuk akun itu. "
  + C("~/.codex/auth.json") + " serta riwayat Codex CLI dan VS Code tetap utuh, dan login di sini tidak membuat "
  "aplikasi itu logout.")
P("<b>Timer mengambilnya sendiri.</b> Jika timer balance terpasang, putaran berikutnya ikut menyeimbangkan akun Codex "
  "(riwayat pemakaian, urutan, istirahat, peringatan) tanpa " + C("setup") + " kedua. Pada timer dari 3.10.2 atau "
  "lebih lama, jalankan sekali " + C("hermes account openai-codex setup --timer") + "; " + C("doctor") + " "
  "memberitahunya.")
note("<b>Memakai akunnya adalah pengaturan Hermes.</b> " + C("add") + " hanya memasukkan akun ke pool. Profil memakai "
     "Codex bila " + C("config.yaml") + " profil itu menyebutnya: sebagai model utama, di " + C("fallback_providers")
     + ", atau untuk gambar (" + C("image_gen.provider: openai-codex") + "). Cek " + C("hermes config")
     + " tiap profil bila ingin tahu ke mana kuota Codex terpakai.")

H1("7. Referensi perintah")
code("""
hermes account <provider> <action> [target] [options]

  list                                  akun dalam rotasi dan yang diparkir
  check                                 kesehatan: mati, limit, label salah, duplikat
  usage                                 pemakaian live per akun, juga yang diparkir
  who      [--minutes N]                sesi mana memakai akun apa (default 30 menit)
  report   [--hours N] [--chart]        beban dan token per akun, bot, model, harga API;
                                        --chart: beban per jam 7 hari terakhir
  add      <email> [--key] [--yes]      tambah akun: terverifikasi, tanpa duplikat
           [--device]                   openai-codex: kode perangkat, bukan browser
  remove   <target> [--yes]             hapus login akun (akun parkir juga)
  park     <target> [--until T]         keluarkan akun dari rotasi
  unpark   <target>                     kembalikan akun yang diparkir
  schedule [<target> --every SPEC]      parkir akun tiap minggu; tanpa target: daftar jadwal
  unschedule <target>                   hapus jadwal parkir akun
  relogin  <target> [--yes] [--device]  login ulang, terverifikasi, label dan posisi tetap
  balance  [--dry-run] [--threshold N]  urutkan, istirahatkan >= N% (90), pulihkan, alert
  strategy [<nama>] [--only P,...]      strategi rotasi Hermes per profil: lihat atau ubah
  sessions [--hours N]                  sesi (tugas) dengan token terbanyak, beserta harga API
  log      [--hours N]                  apa yang diubah timer, perintah, dan halaman
  doctor                                periksa strategi, timer, file, pool, peringatan
  notify   [status|test|summary|...]    peringatan (desktop, Telegram), ringkasan harian
  wake     [<target>[,...]] [--dry-run] mulai jendela 5 jam akun yang menganggur sekarang
           status|models|auto-on|auto-off|model=<id>
                                        pengaturan dan jendela tiap akun; otomatis lewat timer
  privacy  [on|off|status]              sensor email di output, peringatan, dan halaman
  help                                  bantuan

hermes account all balance [--dry-run] [--threshold N]   semua provider berakun (timer)
""")
P("<b>Target</b> adalah label akun (email), nomor urut di " + C("list") + ", atau id. " + C("unpark")
  + " menerima label atau id. Contoh output di bawah berdasarkan pool sungguhan, dengan nama akun diganti.")
table([
    ["Aksi", "Mengubah?", "Aksi", "Mengubah?"],
    [C("list") + ", " + C("check") + ", " + C("who") + ", " + C("report") + ", " + C("sessions") + ", " + C("log")
     + ", " + C("doctor") + ", " + C("help"),
     "Tidak", C("add") + ", " + C("remove") + ", " + C("park") + ", " + C("unpark") + ", " + C("relogin") + ", "
     + C("balance"), "Ya"],
    ["", "", C("schedule") + ", " + C("unschedule") + ", " + C("strategy &lt;nama&gt;"), "Pengaturan"],
    [C("usage"), "Tidak*", C("notify") + ", " + C("privacy") + ", " + C("wake auto-on/model="), "Pengaturan"],
    ["", "", C("wake"), "Request model kecil"],
], [0.36, 0.14, 0.36, 0.14])
P("* " + C("usage") + " memperbarui access token yang kedaluwarsa, sama seperti yang Hermes lakukan saat akun dipakai.")

H2("7.1 list")
code("""
$ hermes account anthropic list
[anthropic] in rotation (8):
  #1  erin@example.com                   id=12e90b  status=ok
  #2  frank@example.com                  id=025bb6  status=ok
  ...
  #8  heidi@example.com                  id=36c28f  status=ok
[anthropic] parked (1):
  -   ivan@example.com                   id=9e95ee  since 2026-10-10 18:07
""")
P("Urutan ini adalah urutan akun yang diambil sesi baru. Untuk park bertanggal, baris parkir juga menampilkan "
  + C("until ...") + ".")
H2("7.2 check")
code("""
$ hermes account anthropic check
[anthropic] in rotation: 8   parked: 1
  OK #1 id=12e90b  label=erin@example.com
        account : erin@example.com
  ...
  -- parked  id=9e95ee  label=ivan@example.com  (since 2026-10-10 18:07)
  All accounts in rotation are healthy.
""")
P(C("account") + " adalah email asli dari provider (butuh adapter). Masalah muncul sebagai baris " + C("issue")
  + ", dan exit code 1 jika ada akun yang perlu perhatian.")
table([
    ["Issue", "Arti", "Tindakan"],
    [C("DEAD: sign in again"), "Provider menolak refresh token", C("relogin &lt;target&gt;") + " (7.9)"],
    [C("RATE LIMITED (HTTP 429)"), "Limit dari provider sendiri", "Tunggu reset; Hermes memakai akun lain"],
    [C("BENCHED by balance"), "Diistirahatkan karena ≥ ambang", "Tidak perlu: dilepas saat reset"],
    [C("COOLING DOWN"), "Refresh token gagal, biasanya jaringan putus", "Tidak perlu: dicoba ulang oleh balance"],
    [C("WRONG LABEL"), "Label berbeda dari akun yang login", C("relogin") + " di browser akun itu, atau " + C("remove")],
    [C("DUPLICATE"), "Akun yang sama terdaftar dua kali", C("remove &lt;id&gt;") + " salah satunya"],
], [0.27, 0.38, 0.35])
H2("7.3 usage")
code("""
$ hermes account anthropic usage
[anthropic] 5-hour usage
  account                            state     used                          resets
  -- in rotation --
  frank@example.com                  active      2%  [....................]  21:00
  erin@example.com                   active      3%  [....................]  20:10
  dave@example.com                   active      3%  [....................]  21:30
  ...
  heidi@example.com                  active     17%  [###.................]  19:50
  -- parked (not used by Hermes) --
  ivan@example.com                   PARKED     29%  [=====...............]  20:30
""")
LI(["Angkanya sama dengan \"Current session\" di pengaturan pemakaian claude.ai. Untuk " + C("openai-codex")
    + ", baris diakhiri kedua jendela, misalnya " + C("(5h 12% · week 78%)") + ", dan yang lebih ketat yang dipakai.",
    "Kolom state: " + C("active") + ", " + C("BENCHED") + " (diistirahatkan balance), " + C("LIMITED")
    + " (limit dari provider), " + C("PARKED") + " (bar " + C("=") + "), " + C("DEAD") + ".",
    "Jika endpoint usage tidak menjawab, baris menampilkan nilai terakhir yang dicatat timer, misalnya "
    + C("(last known, 3 min ago)") + ": paling lama 15 menit dan hanya selama jendelanya belum reset. Jika tidak "
    "ada, alasannya yang tampil, misalnya " + C("n/a (usage endpoint rate-limited, retry in a few minutes)")
    + " atau " + C("n/a (sign-in rejected (401))") + ". Entri API key: " + C("API key: no account usage") + ".",
    "Access token yang kedaluwarsa di-refresh dulu, oleh Hermes sendiri (" + C("try_refresh_matching") + "), yang "
    "langsung menyimpan pasangan token baru di pool-nya (refresh token hanya bisa dipakai sekali). Termasuk akun "
    "parkir: akun parkir tetap login. Bila provider menolak refresh token akun parkir, barisnya berbunyi "
    + C("sign-in expired: hermes account &lt;provider&gt; remove &lt;akun&gt;, then add &lt;akun&gt;") + ".",
    "Baris terakhir adalah perkiraan (bagian 9): kapan semua akun ≥ 90% jika laju satu jam terakhir berlanjut."])
H2("7.4 who")
code("""
$ hermes account anthropic who
[anthropic] sessions active in the last 30 min: 2
  erin@example.com                   (idle)
  frank@example.com                  (idle)
  ...
  heidi@example.com
      worker-2             cli       20261010_181340_51b808 claude-sonnet-5-5    4m ago
      worker-1             cli       20261010_181338_ad9f75 claude-sonnet-5-5    6m ago
$ hermes account anthropic who --minutes 120     # jendela waktu lain
""")
LI(["Kolom: profil, platform, id sesi, model, panggilan API terakhir.",
    "Data berasal dari pelacak sesi, yang mencatat sesi setelah setiap panggilan API ke model.",
    "Jika sesi pindah akun karena limit, muncul keterangan " + C("(moved from ...)") + ".",
    "Sesi yang sudah berjalan sebelum plugin dipasang baru muncul setelah " + C("/reset") + ", atau setelah "
    "gateway/desktop di-restart."])
H2("7.5 report")
code("""
$ hermes account anthropic report --hours 24
[anthropic] usage report: last 24h (288 snapshots, 23.9h covered, from 10-10 06:20)
  'used' adds up 5-hour-window percent: 100 = one full 5-hour window.
  account                              used  share  peak  time >= 90%    tokens     API $
  bob@example.com                       126    27%   60%         0 min     2.7M     $1.53
  carol@example.com                     117    25%   60%         0 min     2.8M     $1.45
  ...
  total                                 461                               10.9M     $5.66
  Tokens through Hermes: 18.8k input, 252.3k output, 10.1M cache read, 567.8k cache write
  647 requests.
  API $ = these tokens at the provider's API list prices (a subscription is billed flat).
  By profile (bot)                  tokens  requests     API $  share
    worker-1                          5.6M       353     $2.54    51%
    worker-2                          2.4M       136     $1.10    22%
    default                           1.9M       102     $1.72    17%
    worker-3                          1.1M        56     $0.29    10%
  By model                          tokens  requests     API $  share
    claude-sonnet-5-5                 8.0M       489     $3.64    73%
    claude-opus-5-5                   1.9M       102     $1.72    17%
    claude-haiku-4-5                  1.1M        56     $0.29    10%
  Busiest hours: 08:00-09:00 (26), 10:00-11:00 (24), 12:00-13:00 (24)
  Time with EVERY account >= 90%: 0 min
  Forecast: At the last hour's pace (12% of one 5-hour window per hour), the 4 accounts
  last beyond the next 5 hours.
  Load by hour for the last 7 days: hermes account anthropic report --chart
""")
LI([C("used") + ": total kenaikan pemakaian. 100 berarti setara satu jendela 5 jam penuh. " + C("peak")
    + ": nilai tertinggi. " + C("time >= 90%") + ": berapa lama akun hampir habis.",
    C("tokens") + ": jumlah token yang dikirim dan diterima Hermes lewat akun itu selama periode laporan (input, output, "
    "cache read, dan cache write dijumlahkan). Baris di bawah tabel merinci totalnya. Pelacak sesi menghitungnya di "
    "setiap panggilan API mulai versi 1.1.0; jika periode dimulai lebih awal, baris itu menyebut " + C("counted since")
    + ". " + C("-") + " berarti belum ada panggilan yang terhitung.",
    C("used") + " dan " + C("tokens") + " mengukur hal berbeda. " + C("used") + " adalah persentase dari provider: "
    "mencakup pemakaian akun di aplikasi lain (claude.ai, Claude Code) dan memberi bobot berbeda per jenis token "
    "(cache read jauh lebih murah daripada token output). " + C("tokens") + " hanya menghitung Hermes di komputer ini.",
    "Dengan data minimal 2 jam dan beban nyata, laporan memberi saran: jika <b>semua akun ≥ 90%</b> pernah terjadi "
    "bersamaan, laporan menyarankan menambah akun; jika satu akun menanggung lebih dari separuh beban, laporan "
    "mengarahkan ke " + C("who") + ".",
    "Default 24 jam (" + C("--hours N") + "). Riwayat mencakup minimal 14 hari terakhir."])
P("<b>API $</b> adalah nilai token itu jika lewat API provider, dengan harga daftar per model (input, output, cache "
  "read, dan cache write masing-masing dengan harganya sendiri). Langganan (Pro, Max, Team) dibayar tetap, jadi angka "
  "ini menunjukkan nilai pemakaian, bukan tagihan. Harganya diambil dari Hermes sendiri: daftar harga bawaannya, atau "
  "cache models.dev-nya; plugin tidak membuat permintaan untuk itu. Tanda " + C("+") + " berarti sebagian token "
  "tidak punya harga yang diketahui (model tanpa harga, atau token yang dihitung " + C("account-pool-tracker")
  + " sebelum 1.3.0, pelacak terpisah di 3.x, yang belum "
  "mencatat model); token itu tidak dihitung, bukan ditebak.")
P(C("By profile (bot)") + " dan " + C("By model") + " membagi token yang sama menurut profil Hermes yang "
  "memanggil dan menurut modelnya. Token dari " + C("account-pool-tracker") + " yang lebih lama dari 1.3.0 tampil sebagai " + C("(older tracker, no name)")
  + ": dihitung sebelum update itu, atau oleh proses yang masih memakai pelacak lama sampai di-restart. Token ini "
  "hilang dari laporan dalam 8 hari.")
P(C("report --chart") + " menggambar beban per jam selama 7 hari terakhir: satu baris per hari, satu kolom per jam "
  "(waktu lokal). Makin gelap, makin besar bebannya; " + C("·") + " berarti kosong. Blok pertama adalah kuota "
  "terpakai (dari riwayat timer), blok kedua token lewat Hermes.")
code("""
$ hermes account anthropic report --chart
[anthropic] load by hour (local time; one row per day, one column per hour)
  Load by hour, last 7 days: quota used (5-hour-window percent). Darkest = 26 in one hour.
             00 03 06 09 12 15 18 21
  Mon 10-05  ························
  ...
  Sat 10-10  ······▒██▓█▓██▓▓▓▓█▓▓█▓▓
  Sun 10-11  ▓█▓███░·················
  Load by hour, last 7 days: tokens through Hermes. Darkest = 710.6k in one hour.
""")
H2("7.6 park / unpark")
code("""
$ hermes account anthropic park frank@example.com                    # sampai di-unpark
$ hermes account anthropic park frank@example.com --until 17:00      # besok jika 17:00 lewat
$ hermes account anthropic park frank@example.com --until +2h        # juga: 90m, 1d
$ hermes account anthropic park frank@example.com --until '2026-10-12 08:00'
$ hermes account anthropic unpark frank@example.com
""")
LI(["Park membiarkan akun dan loginnya di pool Hermes dan meminta Hermes melewatinya: Hermes menandai akun "
    "exhausted dengan alasan " + C("parked") + " dan waktu reset. Waktunya jam " + C("--until") + ", atau 30 hari "
    "untuk parkir tanpa jam; putaran balance memperpanjangnya lagi ke 30 hari begitu sisanya kurang dari 15 hari, jadi parkir bertahan sampai Anda "
    "unpark. " + C("hermes auth list") + " menampilkan akun itu sebagai exhausted, dan " + C("usage") + " tetap "
    "menampilkan pemakaiannya.",
    "Plugin menyimpan daftar parkir, " + C("account-pool-parking.json") + ", berisi label, id, dan waktu saja. "
    "Park bertanggal berakhir pada waktunya: Hermes mengembalikan akun itu sendiri, dan putaran timer berikutnya "
    "membersihkannya dari daftar. Akun aktif terakhir tidak bisa diparkir.",
    "Jika ada yang mengembalikan akun parkir lebih awal (" + C("hermes auth reset") + ", atau Hermes melihat kuota "
    "Codex kembali), putaran balance berikutnya memarkirnya lagi dan mencatatnya; sampai saat itu " + C("doctor")
    + " menyebutnya. Akun yang dihapus dari pool saat diparkir tampil sebagai " + C("not in the pool") + " dan "
    "dilupakan pada putaran balance berikutnya.",
    "Contoh kegunaan: menyisakan kuota akun tertentu untuk Anda pakai sendiri di claude.ai, atau mengistirahatkan "
    "akun yang mendekati limit mingguan. Untuk jam yang sama setiap minggu, pakai " + C("schedule") + " (7.7).",
    "Jendela 5 jam akun yang diparkir tetap berjalan: pekerjaan sesaat sebelum diparkir tetap terhitung sampai "
    "reset, dan aplikasi lain yang login ke akun itu masih bisa memakainya. Karena itu timer tetap membaca "
    "pemakaiannya (membaca pemakaian bukan request model, tidak memakai kuota), dan Hermes me-refresh tokennya saat "
    "kedaluwarsa. Halaman menampilkan pemakaian, jam reset, dan garis tren akun parkir seperti akun lain.",
    "Angka ini tidak ikut angka pool (urutan, peringatan, laporan, perkiraan, grafik per jam, ringkasan harian), "
    "karena yang memakai akun parkir bukan Hermes."])
H2("7.7 schedule / unschedule", need=70)
code("""
$ hermes account anthropic schedule dave@example.com --every "mon-fri 09:00-17:00"
Schedule saved [anthropic]: dave@example.com is parked Mon-Fri 09:00-17:00.
Next: Mon 10-12 09:00.
Unparking it by hand inside a window keeps it in rotation until the next window.
Undo: hermes account anthropic unschedule dave@example.com

$ hermes account anthropic schedule                # daftar jadwal dan keadaannya
$ hermes account anthropic unschedule dave@example.com
""")
LI(["Jadwal memarkir akun di hari dan jam tertentu, setiap minggu. Cocok jika Anda memakai akun itu sendiri di "
    "claude.ai atau Claude Code pada jam tetap dan ingin Hermes tidak menyentuh kuotanya.",
    C("--every") + " berisi hari dan rentang jam (waktu lokal). Hari: " + C("mon") + " sampai " + C("sun")
    + ", rentang (" + C("mon-fri") + ", " + C("fri-mon") + "), daftar (" + C("sat,sun") + "), " + C("daily")
    + ", " + C("weekdays") + ", " + C("weekend") + ". Rentang yang selesai sebelum mulai melewati tengah malam: "
    + C("daily 22:00-06:00") + ". Satu jadwal per akun; menyimpan lagi berarti mengganti.",
    "Timer yang menjalankannya: pada putaran pertama setelah jendela mulai, akun diparkir sampai akhir jendela "
    "(sama dengan " + C("park --until") + "), lalu kembali pada putaran pertama setelah jendela berakhir. "
    + C("list") + " dan halaman menandainya " + C("(schedule)") + ".",
    "Setiap jendela dijalankan sekali. Jika Anda meng-unpark akun di tengah jendela, akun tetap dalam rotasi sampai "
    "jendela berikutnya. Akun yang Anda parkir sendiri tidak diubah.",
    "Akun aktif terakhir tidak pernah diparkir; timer mencoba lagi di putaran berikutnya.",
    C("unschedule") + " menghapus jadwal. Jika saat itu jadwal sedang memarkir akunnya, akun tetap diparkir sampai "
    "jendela berakhir; " + C("unpark") + " untuk mengembalikannya lebih cepat.",
    "Jadwal disimpan di " + C("account-pool.json") + " berdasarkan label, jadi tetap berlaku setelah "
    + C("relogin") + ". Jadwal yang akunnya sudah dihapus tampil " + C("not in the pool") + " dan " + C("doctor")
    + " memperingatkannya."])
H2("7.8 balance")
code("""
$ hermes account anthropic balance --dry-run       # rencana saja
$ hermes account anthropic balance                 # jalankan (otomatis tiap 5 menit)
2026-10-10 18:39:48 [anthropic] balance (dry run):
  - order: frank(2%) > erin(3%) > dave(3%) > alice(4%) > carol(5%) > bob(7%) > ...
""")
P("Timer menjalankan " + C("hermes account all balance") + ": semua provider yang punya akun (di rotasi atau "
  "parkir), satu per satu. Provider yang gagal tidak menghentikan yang lain; exit code menandai kegagalannya. "
  + C("--threshold N") + " (1 sampai 100, default 90) mengatur ambang istirahat. Baris lain yang bisa muncul: "
  + C("unpark X (park --until ... reached)") + ", " + C("recovered: X (token refresh retried)") + ", "
  + C("bench X (93%) until 17:10") + ", " + C("release X (40%)") + ". Cara kerjanya di bagian 10.")
H2("7.9 relogin")
code("""
$ hermes account anthropic relogin alice@example.com
Re-login alice@example.com (anthropic, id=0b1e86)
  1. Open the sign-in link in a browser that is signed in as THIS account:
     its own Chrome profile, or a private / incognito window.
  2. Make sure the page says: Logged in as alice@example.com  (otherwise: Switch account)
     "Sign in again to continue" is normal when that browser login is old.
  3. Authorize, then paste the code back here.
The old entry is replaced only if the new sign-in really is that account.
Continue? [y/N]
""")
LI(["Dipakai setelah " + C("DEAD") + " atau " + C("WRONG LABEL") + ". Login baru ditambahkan <b>dulu</b>, lalu "
    "email aslinya dicek.",
    "Jika cocok, entri lama dihapus dan entri baru menempati posisi yang sama dengan label yang sama. Jika berbeda, "
    "login baru dibuang dan entri lama tidak disentuh.",
    "Akun yang sedang diparkir harus di-" + C("unpark") + " dulu. " + C("--yes") + " melewati konfirmasi. "
    "Ctrl+C membatalkan dengan bersih.",
    "Tanpa terminal (cron, shell milik agent), " + C("add") + " dan " + C("relogin") + " langsung berhenti dengan "
    "pesan " + C("needs a terminal") + " beserta perintah yang harus dijalankan di terminal atau tombol di halaman, "
    "bahkan dengan " + C("--yes") + ". Tanpa itu, mereka bisa menunggu kode login selamanya."])
H2("7.10 strategy", need=80)
code("""
$ hermes account anthropic strategy
[anthropic] rotation strategy per profile (Hermes: credential_pool_strategies.anthropic):
  default                      fill_first
  worker-1                     fill_first
  worker-2                     round_robin
  ...
$ hermes account anthropic strategy fill_first
Rotation strategy [anthropic]: fill_first in worker-2 (was round_robin).
New sessions there use it from now; running sessions keep their account.
$ hermes account anthropic strategy round_robin --only worker-2
WARNING: round_robin ignores the order balance sets, so a new session can start on a nearly
full account.
Set round_robin in worker-2? [y/N]
""")
LI(["Menampilkan atau mengubah " + C("credential_pool_strategies.&lt;provider&gt;") + " di semua profil, atau hanya "
    "di profil yang disebut dengan " + C("--only") + " (dipisah koma). Daftarnya juga menjelaskan keempat strategi.",
    "Nilai ditulis dengan " + C("hermes config set") + " milik Hermes, satu profil demi satu profil, lalu dibaca "
    "ulang. Isi " + C("config.yaml") + " yang lain tidak berubah. Profil yang nilainya sudah sama tidak disentuh; profil "
    "tanpa pengaturan ini sudah memakai " + C("fill_first") + ", jadi " + C("strategy fill_first") + " membiarkannya.",
    "Sesi baru langsung memakai strategi baru tanpa restart, karena Hermes membacanya setiap kali memuat pool. Sesi "
    "yang berjalan tetap di akunnya.",
    "Selain " + C("fill_first") + " ada konfirmasi (" + C("--yes") + " melewatinya), karena strategi lain "
    "mengabaikan urutan dari " + C("balance") + ". Output-nya lalu menyebut perintah untuk kembali.",
    "Halaman melakukan hal yang sama dari tautan " + C("rotation: ...") + " di header (bagian 8.3)."])
H2("7.11 doctor", need=85)
code("""
$ hermes account anthropic doctor
[anthropic] doctor
  OK    strategy fill_first in 6 profiles
  OK    every profile uses the shared account pool
  OK    session tracking active in every profile
  OK    running sessions count with session tracking 4.0.1
  OK    Accounts page backend enabled in every profile
  OK    account-pool-parking.json permissions 600
  OK    balance timer active, last run 2026-10-10 18:36:09 WIB
  OK    usage history last written 4 min ago
  OK    8 accounts in rotation, 1 parked
  OK    usage endpoint reachable
  OK    alert channels: desktop, telegram via default to the bot's home channel (...)
  0 failure(s), 0 warning(s).
""")
P("Jalankan setelah instalasi, setelah update Hermes, atau saat bot berperilaku aneh. Setiap baris FAIL atau WARN "
  "menyertakan perbaikannya. Pelacak sesi dimuat saat proses mulai, jadi setelah update gateway, Hermes Desktop, dan sesi "
  "panjang masih memakai pelacak lama; doctor lalu memberi WARN " + C("session tracker 4.0.1 is not loaded yet by: ...")
  + " beserta restart yang dibutuhkan masing-masing. Token tanpa nama bot dalam setengah jam terakhir berarti "
  + C("account-pool-tracker") + " 1.2.0 atau lebih lama masih berjalan. Untuk akun parkir, doctor memberi WARN bila "
  "Hermes memasukkannya lagi ke rotasi, bila akunnya keluar dari pool, bila Hermes menahan akun sebagai parkir "
  "padahal daftar parkir tidak menyebutnya, dan bila ada parkir tanpa jam selesai sementara timer mati. Untuk "
  "Telegram: WARN bila bot belum punya home channel. Sisa " + C("account-pool-tracker") + " dari 3.x: WARN dengan "
  + C("Fix: hermes account &lt;provider&gt; setup") + ". Profil dengan strategi lain adalah FAIL (perbaikan: " + C("strategy fill_first")
  + "); nilai yang tidak dikenal Hermes hanya WARN, karena Hermes lalu memakai " + C("fill_first") + "."
  " Exit code 1 jika ada FAIL. Untuk provider tanpa akun: "
  + C("not in use, nothing to check") + ".")
H2("7.12 notify")
code("""
hermes account anthropic notify                         # status
hermes account anthropic notify test                    # kirim pesan tes ke semua saluran
hermes account anthropic notify desktop-off             # / desktop-on
hermes account anthropic notify telegram-off            # / telegram-on
hermes account anthropic notify telegram-to=<id chat>   # kirim ke chat ini; home: home channel
hermes account anthropic notify telegram-via=<profil>   # bot profil mana yang mengirim
hermes account anthropic notify daily=08:00             # ringkasan harian; daily-off: mati
hermes account anthropic notify summary                 # kirim ringkasan sekarang
hermes account anthropic notify bots=15                 # peringatan bot mulai $15/jam
hermes account anthropic notify bots-off                # / bots-on
""")
P("Penjelasan lengkap di bagian 9.")
H2("7.13 sessions", need=80)
code("""
$ hermes account anthropic sessions --hours 24
[anthropic] sessions by API price, last 24 h (23 sessions)
  profile              source    tokens requests     API $  title
  worker-1             kanban     12.8M      340    $18.90  Shipping: admin page (t_5f2e91)
  worker-2             telegram    9.5M      272    $12.52  Daily stock digest
  default              desktop     2.1M       61     $4.10  Plan the release
  ...
  20 more: 6.3M tokens, $7.75.
  Total: 30.7M tokens in 801 requests, $43.27 at API list prices.
""")
LI(["Sesi dengan token terbanyak dalam periode itu (maksimal 15), diurutkan menurut harga API. Dipakai untuk melihat "
    "tugas atau obrolan mana yang menghabiskan token sebuah bot di " + C("report") + ", atau setelah peringatan bot "
    "(bagian 9).",
    "Token per sesi dihitung mulai panggilan API pertama pelacak sesi (di 3.x: " + C("account-pool-tracker")
    + " 1.5.0 ke atas). Periode yang dimulai lebih awal menyebut " + C("counted per session since ...")
    + "; bot yang masih memakai pelacak lebih lama belum muncul di sini sampai di-restart (" + C("doctor")
    + " menyebut prosesnya).",
    C("title") + " dan " + C("source") + " (cli, telegram, kanban, cron, desktop, ...) diambil dari daftar sesi Hermes "
    "sendiri di " + C("state.db") + " tiap profil, hanya dibaca. Sesi tanpa judul tampil dengan sumber dan id-nya. Tugas "
    "Kanban ditambahkan dalam kurung bila sesi itu menjalankan tugas.",
    "Bloknya sama dengan " + C("report") + ": 15 menit, 8 hari terakhir. Token sebelum periode tidak dihitung, jadi sesi "
    "panjang hanya tampil bagiannya di dalam periode."])
H2("7.14 log", need=70)
code("""
$ hermes account anthropic log --hours 24
[anthropic] activity, last 24 h: 4 events (newest last)
  10-11 08:05  timer  balance     bench alice@example.com (91%) until 10:40
  10-11 09:00  timer  schedule    schedule: parked dave@example.com until 17:00 (Mon-Fri ...)
  10-11 10:12  page   strategy    Rotation strategy [anthropic]: fill_first in worker-3 (...)
  10-11 10:40  timer  balance     release alice@example.com (12%)
""")
LI(["Apa yang berubah di pool dan pengaturannya, dan siapa yang mengubah: " + C("timer") + " (timer balance), "
    + C("cli") + " (perintah " + C("hermes account") + "), atau " + C("page") + " (halaman Accounts).",
    "Dicatat: istirahat dan lepas, unpark bertanggal dan parkir terjadwal, pemulihan refresh token, peringatan yang "
    "dikirim, " + C("park") + ", " + C("unpark") + ", " + C("remove") + ", " + C("add") + ", " + C("relogin") + ", "
    + C("schedule") + ", " + C("unschedule") + ", " + C("strategy") + ", dan pengaturan peringatan. Tidak dicatat: "
    "perintah baca (" + C("list") + ", " + C("usage") + ", " + C("report") + ", ...) dan urutan baru setelah setiap "
    "balance, yang berubah hampir di setiap putaran.",
    "Disimpan di " + C("account-pool-activity.jsonl") + ", izin 600, 30 hari. Isinya label, waktu, dan pesan perintah "
    "itu sendiri, tidak pernah kredensial."])
H2("7.15 setup", need=40)
code("""
hermes account anthropic setup                     # profil, pelacak sesi; rencana, lalu tanya
hermes account anthropic setup --timer --strategy  # plus timer 5 menit dan fill_first
hermes account anthropic setup --undo              # tarik kembali bagian profil dan timer
""")
P("Mengerjakan yang tidak dikerjakan instalasi plugin: backend halaman Accounts dan pelacak sesi di setiap profil "
  "(dan, saat update dari 3.x, menghapus " + C("account-pool-tracker") + "), "
  "timer, dan strategi. Penjelasan lengkap di bagian 4.3. Pertanyaan " + C("[y/N]") + " di semua perintah dijawab "
  "<b>tidak</b> jika tidak ada terminal (" + C("no terminal to answer, so no") + ", exit 1); " + C("--yes")
  + " tetap melewatinya.")
H2("7.16 wake", need=90)
code("""
$ hermes account anthropic wake --dry-run
2026-10-12 07:04:56 [anthropic] wake (dry run): 3 to wake, 0 failed, 5 left alone.
  - would wake carol@example.com
  - would wake erin@example.com
  - would wake heidi@example.com
  - skip frank@example.com: window running, resets 08:34
  ...

$ hermes account anthropic wake
2026-10-12 07:04:56 [anthropic] wake: 3 woken, 0 failed, 5 left alone.
  - woke carol@example.com (claude-haiku-4-5): its 5-hour window starts now,
    resets about 12:04
  ...
The next balance run (within 5 minutes) reads the new reset times.

$ hermes account anthropic wake auto-on
Automatic wake on [anthropic]: the balance timer wakes an account in rotation whose
5-hour window is not running, with one tiny request to claude-haiku-4-5.

$ hermes account anthropic wake models
[anthropic] models for the wake request (the account's own list, read now):
  claude-opus-4-5-20251101
  claude-sonnet-4-5-20250929
  claude-haiku-4-5-20251001
Now: claude-haiku-4-5 (default). Set: hermes account anthropic wake model=<id>|model=default
""")
P("Jendela 5 jam sebuah akun mulai saat request pertamanya (bagian 5). Akun yang menganggur sampai 10:00 lalu dipakai "
  "berat bisa penuh pukul 11:00 dan tetap penuh sampai 15:00. Bila dibangunkan pukul 07:00, jendelanya reset pukul "
  "12:00, bukan 15:00: pekerjaan yang kena limit pukul 11:00 menunggu satu jam, bukan empat. " + C("wake")
  + " mengirim request pertama itu sekarang: satu request lewat akun tersebut yang meminta jawaban satu kata.")
table([
    ["Provider", "Request wake", "Tanda jendela tidak berjalan"],
    [C("anthropic"), C("claude-haiku-4-5") + ", satu token output, lewat klien Anthropic milik Hermes sendiri (header "
     "dan identitas Claude Code sama dengan sesi Hermes)", "Jawaban pemakaian tidak punya jam reset"],
    [C("openai-codex"), "Model terkecil yang tersedia untuk akun itu (dari daftar modelnya, seperti dibaca Hermes), "
     "reasoning rendah, jawaban satu kata lewat endpoint Responses Codex", "0% dengan reset tepat 5 jam lagi yang ikut "
     "bergeser setiap dibaca. Jendela 5 jam yang dipakai, walau jendela mingguan lebih penuh"],
], [0.16, 0.50, 0.34])
LI(["<b>Akun mana.</b> Akun dalam rotasi yang jendelanya tidak berjalan. Jendela yang sedang berjalan tidak mendapat "
    "apa-apa dari wake, jadi dibiarkan; begitu juga akun yang diistirahatkan, kena limit, mati, API key, dan diparkir.",
    "<b>Tanpa target</b>, wake membaca pemakaian tiap akun dulu (satu request pemakaian per akun, seperti "
    + C("usage") + ") lalu membangunkan yang menganggur. <b>Dengan target</b> (label, nomor urut, atau id; beberapa "
    "dipisah koma) akun itu dibangunkan kecuali jendelanya diketahui sedang berjalan, juga bila pemakaiannya tidak "
    "terbaca. " + C("--dry-run") + " menampilkan rencananya saja.",
    C("wake status") + " menampilkan pengaturan, model, jendela tiap akun dari putaran balance terakhir, dan wake "
    "terakhirnya. Tanpa request apa pun.",
    C("wake auto-on") + " membuat timer balance membangunkan akun begitu jendelanya tidak berjalan. Selama jendela "
    "berjalan tidak ada yang dikirim, jadi paling banyak sekitar 5 request per akun per hari. Akun yang dibangunkan "
    "dalam satu jam terakhir tidak dibangunkan lagi, jadi wake yang tidak memulai jendela hanya memakan satu request per "
    "jam, bukan tiap 5 menit. " + C("wake auto-off") + " mematikannya. Butuh timer; " + C("doctor")
    + " memperingatkan bila timer mati atau ada wake yang gagal dalam 6 jam terakhir.",
    C("wake model=&lt;id&gt;") + " memakai model lain; " + C("model=default") + " kembali ke pilihan adapter.",
    C("wake models") + " menampilkan model yang tersedia untuk akun itu, dibaca langsung dari provider lewat akun "
    "pertama dalam rotasi yang login-nya aktif (akun kedua bila yang pertama gagal). Membaca daftar model bukan "
    "request model, jadi tidak memakai kuota. Anthropic: daftar " + C("/v1/models") + " yang juga dibaca pemilih "
    "model Hermes. Codex: daftar akun tanpa varian " + C("-900k") + " dan " + C("spark") + " (Spark punya limit "
    "sendiri, jadi request ke sana tidak memulai jendela 5 jam). Baris terakhir menyebut model yang dipakai. Daftarnya "
    "disimpan di " + C("account-pool-state.json") + ": bila provider tidak terjangkau, yang tersimpan ditampilkan "
    "beserta alasannya, dan " + C("model=&lt;id&gt;") + " yang tidak ada di daftar tetap disimpan dengan catatan.",
    "Wake yang gagal menyebut alasannya (" + C("rate-limited") + ", " + C("sign-in rejected (401)") + ", "
    + C("model ... not accepted") + ") dan perintah keluar dengan exit 1. Setiap wake, berhasil atau gagal, masuk log "
    "aktivitas.",
    "<b>Yang tidak dilakukan.</b> Wake tidak menambah kuota. Limitnya tetap; hanya awal jendela yang maju. Pool yang "
    "akunnya sibuk sepanjang hari jendelanya sudah berjalan, jadi tidak ada yang perlu dibangunkan."])
H2("7.17 privacy (sensor email)", need=70)
code("""
$ hermes account anthropic privacy on
Email masking on: the Accounts page, alerts and the output of hermes account show emails
as al•••e@e•••.com, for every provider. Targets still take the full email, the list number
or the id.

$ hermes account anthropic list
[anthropic] in rotation (8):
  #1  ca•••l@e•••.com                    id=2a1b2c  status=ok
  #2  e•••@e•••.com                      id=4a1b2c  status=ok
  #3  he•••i@e•••.com                    id=7a1b2c  status=ok
  ...
""")
P("Untuk screenshot, berbagi layar, dan menempel output ke chat.")
LI(["<b>Aturannya.</b> Dua huruf pertama dan huruf terakhir nama (hanya huruf pertama untuk nama empat huruf atau "
    "kurang), huruf pertama domain, dan akhiran domain: " + C("alice@example.com") + " menjadi "
    + C("al•••e@e•••.com") + ". Cukup untuk membedakan akun Anda sendiri, tidak cukup untuk dibaca orang lain.",
    "<b>Di mana.</b> Semua baris yang dicetak " + C("hermes account") + " (kolom tetap rata), peringatan desktop dan "
    "Telegram, ringkasan harian, dan seluruh halaman Accounts: tabel, kartu, dialog, tooltip, pesan, dan chip status "
    "bar. Tombol mata di header halaman mengubah pengaturan yang sama.",
    "<b>Hanya tampilan.</b> " + C("auth.json") + ", log aktivitas, riwayat, dan file pengaturan tetap menyimpan "
    "email asli, jadi " + C("privacy off") + " langsung menampilkannya lagi, dan " + C("park alice@example.com")
    + " tetap jalan selama email disensor. Backend halaman mengirim label asli ke halaman, dan halaman menyensor yang "
    "ditampilkannya.",
    C("privacy") + " (atau " + C("privacy status") + ") menampilkan pengaturannya. Satu pengaturan untuk semua "
    "provider (" + C("mask_emails") + " di file pengaturan)."])
H2("7.18 help, pesan salah, dan exit code")
code("""
hermes account                 # semua cara ini menampilkan bantuan yang sama
hermes account help
hermes account --help
hermes account anthropic help
""")
table([
    ["Perintah", "Pesan"],
    [C("hermes account anthropic"), "Missing action for provider 'anthropic'."],
    [C("hermes account anthropic lst"), "'lst' is not an action. Did you mean: list?"],
    [C("hermes account anthropic park"), "Missing target. Usage: hermes account anthropic park &lt;email|id&gt;"],
    [C("hermes account anthropic usage --hours 5"), "--hours only applies to: log, report, sessions"],
    [C("... park X --until 25:99"), "Cannot read --until '25:99'. Use HH:MM (e.g. 17:00), +2h, 90m, or 'YYYY-MM-DD HH:MM'."],
    [C("hermes account anthorpic list"), "Unknown provider 'anthorpic'. Providers in your pool: anthropic. All providers: hermes auth list"],
], [0.40, 0.60])
table([
    ["Exit code", "Arti"],
    ["0", "Selesai"],
    ["1", "Perintah jalan dan menemukan masalah: " + C("check") + "/" + C("doctor") + " gagal, login dibuang atau "
     "gagal, remove ditolak, konfirmasi dijawab tidak (atau Ctrl+D, atau tanpa terminal), " + C("add") + "/" + C("relogin") + " tanpa terminal, " + C("notify test") + " atau " + C("notify summary") + " tidak sampai ke saluran mana pun, " + C("unschedule") + " untuk akun tanpa jadwal, " + C("strategy") + " atau langkah " + C("setup") + " yang gagal ditulis, " + C("wake") + " yang gagal untuk suatu akun"],
    ["2", "Cara pakai salah: aksi, provider, target, atau opsi tidak ada atau tidak dikenal"],
    ["130", "Dibatalkan dengan Ctrl+C"],
], [0.14, 0.86], keep=True)

H1("8. Halaman Accounts di Hermes Desktop")
P("Plugin " + C("account-pool") + " juga membawa halaman <b>Accounts</b> untuk Hermes Desktop: pool, pemakaiannya, "
  "siapa memakai akun apa, dan semua aksi " + C("hermes account") + " dalam bentuk tombol. Perintahnya tetap jalan "
  "seperti biasa; halaman memakai kode yang sama.")
H2("8.1 Menyalakan halaman")
OL(["Pasang plugin lalu jalankan " + C("hermes account &lt;provider&gt; setup") + " (atau " + C("install.sh")
    + ", yang menjalankannya). Halaman ikut " + C("account-pool") + "; " + C("setup") + " mencantumkan "
    + C("account-pool") + " di semua profil.",
    "Restart Hermes Desktop. Desktop menjalankan backend halaman bersama plugin lain yang aktif, jadi sebelum "
    "restart ini halaman belum punya data.",
    "Di <b>Capabilities &gt; Plugins</b>, cari <b>account-pool</b> (Agent + Desktop; nama desktop-nya Accounts) dan "
    "nyalakan bagian <b>Desktop</b>. Halaman ini dikirim dalam keadaan mati, jadi belum muncul apa pun sebelum Anda "
    "menyalakannya."])
P("Setelah itu <b>Accounts</b> muncul di sidebar. Command palette (Ctrl+K) punya " + C("Accounts: open the account pool")
  + ", dan chip di status bar juga membuka halaman ini.")
H2("8.2 Kenapa semua profil mencantumkan account-pool")
P("Hermes Desktop menjalankan backend-nya dengan profil yang terakhir Anda pakai (" + C("hermes --profile &lt;nama&gt; serve")
  + "). Backend itu hanya memuat route halaman sebuah plugin jika plugin itu ada di " + C("plugins.enabled")
  + " <b>profil tersebut</b>. Jika " + C("account-pool") + " hanya ada di profil default, halaman jalan saat Desktop "
  "memakai profil default, dan menampilkan " + C("The account-pool backend did not answer") + " saat memakai profil lain.")
P("Karena itu " + C("setup") + " (dan " + C("install.sh") + ") menambahkan " + C("account-pool") + " ke " + C("plugins.enabled") + " semua profil, "
  "dan menautkan " + C("plugins/account-pool") + " profil itu ke salinan profil default. Yang didapat profil dari situ:")
LI(["Agent di sebuah profil memuat plugin dari folder " + C("plugins/") + " milik profil itu sendiri. Di sana "
    + C("register()") + " mengenali profil itu dan hanya menambahkan pelacak sesi (hook " + C("post_api_request")
    + " yang menulis label, id, dan jumlah token). Tanpa perintah dan tanpa tool: " + C("hermes -p &lt;profil&gt; account ...")
    + " tetap perintah yang tidak dikenal, dan bot tidak bisa mengubah pool.",
    "Backend halaman selalu memakai pool bersama di Hermes home default, profil mana pun yang dijalankan Desktop."])
P(C("doctor") + " memeriksa hal ini jika Hermes Desktop punya halamannya: " + C("Accounts page backend enabled in every profile")
  + ", atau peringatan berisi nama profil yang belum mencantumkannya.")
H2("8.3 Isi halaman", need=120)
shot("accounts", "Tab Accounts: delapan akun dalam rotasi beserta pemakaian 5 jam dan bot di tiap akun, dua akun "
     "parkir beserta jam resetnya, dua jadwal parkir, dan perkiraan. Semua akun di gambar adalah data contoh dari tes.")
P("Header berisi pilihan provider, tombol mata untuk sensor email, tombol <b>Live usage</b>, <b>Wake</b>, <b>Balance now</b>, dan <b>Add account</b>. Baris di "
  "bawahnya menunjukkan umur angka pemakaian dan kapan timer jalan berikutnya.")
table([
    ["Tab", "Isi"],
    ["Accounts", "Baris di bawah header menampilkan strategi rotasi Hermes (arahkan kursor untuk penjelasan tiap "
     "strategi, klik untuk mengubahnya); banner menyebut profil yang tidak memakai " + C("fill_first") + " beserta "
     "tombol <b>Use fill_first</b>. Lima kartu: akun dalam rotasi, akun parkir, akun tempat sesi berikutnya mulai beserta pemakaiannya, "
     "jumlah sesi 30 menit terakhir, dan token 24 jam terakhir beserta harga API-nya. Kartu keenam adalah perkiraan "
     "(bagian 9): kapan semua akun ≥ 90% dengan laju satu jam terakhir. Lalu tabel rotasi sesuai urutan pool: status, bar "
     "pemakaian 5 jam, garis tren 5 jam terakhir (arahkan kursor untuk rentangnya dan angka tertinggi 24 jam terakhir), jam reset (" + C("back HH:MM") + " saat diistirahatkan, " + C("not started") + " selama jendela tidak berjalan), "
     "token 24 jam terakhir (arahkan kursor untuk rincian input, output, cache, jumlah request, harga API, model utama, dan "
     "jendela 5 jam yang sedang berjalan), profil yang memakai akun itu "
     "(arahkan kursor untuk melihat sesi, platform, model, sejak kapan sesi itu di akun ini, dan akun asalnya bila pindah), serta tombol <b>Sign in again</b>, <b>Park</b>, "
     "<b>Park on a schedule</b>, <b>Remove</b>. Ikon kalender di sebelah akun menunjukkan jadwalnya. Di bawahnya akun "
     "parkir dengan kolom yang sama: pemakaian 5 jam, garis tren, dan jam reset (timer tetap membacanya; "
     + C("not started") + " bila jendelanya sudah habis), sejak kapan, kapan kembali (" + C("(schedule)") + " bila diparkir jadwal), tombol "
     "<b>Unpark</b>, <b>Park on a schedule</b>, dan <b>Remove</b>. Lalu tabel jadwal parkir beserta keadaannya "
     "sekarang, dengan tombol ubah dan hapus. Peringatan aktif tampil sebagai banner di atas; akun mati mendapat tombol <b>Sign in again</b>, peringatan bot "
     "mendapat tombol <b>See sessions</b>. Banner info "
     "menyebut proses yang masih memakai pelacak lama beserta perbaikannya."],
    ["Report", "Angka " + C("report") + " untuk 24 jam, 3 hari, atau 7 hari: beban per akun, porsi, puncak, waktu "
     "≥ 90%, token dan harga API-nya, jam tersibuk, dan saran. Lalu token per profil (bot), per model, dan per sesi "
     "(daftar " + C("sessions") + ": judul, tugas Kanban, profil, sumber; arahkan kursor ke judul untuk akun, model, "
     "waktu, dan rincian token), serta grafik beban per jam 7 hari terakhir (kuota terpakai atau token; arahkan kursor "
     "ke kotak untuk angkanya)."],
    ["Activity", C("log") + " untuk 24 jam, 3 hari, atau 7 hari, terbaru di atas: kapan, siapa (" + C("timer") + ", "
     + C("cli") + ", " + C("page") + "), dan apa yang terjadi."],
    ["Health", "Status timer, umur riwayat pemakaian, peringatan aktif. <b>Run doctor</b> menjalankan pemeriksaan "
     + C("doctor") + "; <b>Check accounts</b> menjalankan " + C("check") + " dan menampilkan hasilnya."],
    ["Alerts", "Sakelar desktop dan Telegram, profil yang bot-nya mengirim pesan Telegram, ringkasan harian (sakelar dan jam), "
     "peringatan bot (sakelar dan dolar per jam), "
     "<b>Send a test alert</b>, <b>Send the summary now</b>, dan peringatan yang sedang aktif."],
], [0.14, 0.86])
shot("report", "Tab Report: beban dan token per akun, token per bot dan per model dengan harga API.")
shot("activity", "Tab Activity: apa yang diubah timer, perintah, dan halaman.")
P("<b>Park</b> menanyakan kapan akun kembali: saat di-unpark, 1 jam lagi, 2 jam lagi, atau jam yang Anda ketik ("
  + C("17:00") + ", " + C("+90m") + ", " + C("2026-10-12 08:00") + ", format yang sama dengan " + C("--until")
  + "). <b>Park on a schedule</b> menanyakan hari dan jamnya (" + C("09:00") + " sampai " + C("17:00")
  + "), sama dengan " + C("schedule --every") + ". <b>Remove</b> dan <b>Balance now</b> minta konfirmasi dulu. Setiap aksi menampilkan pesan yang sama dengan "
  "perintahnya.")
P("<b>Wake</b> membuka dialog wake: setiap akun dalam rotasi beserta jendela 5 jamnya (" + C("not running") + ", "
  + C("running, resets 11:02") + ") dan wake terakhirnya. Akun yang jendelanya tidak berjalan sudah dicentang; <b>Wake "
  "N accounts</b> membangunkan yang dicentang (sama dengan " + C("wake &lt;id&gt;,&lt;id&gt;") + ") lalu menampilkan "
  "hasilnya. Akun dengan jendela yang berjalan tidak bisa dicentang. Kotak di kepala tabel mencentang semua akun "
  "yang bisa dibangunkan, atau mengosongkan semuanya; isinya tanda strip bila baru sebagian yang dicentang. Bila "
  "semua jendela sedang berjalan, dialog menyebutkannya beserta jam reset paling awal, dan tidak ada yang bisa "
  "dicentang: memang tidak ada yang perlu dibangunkan.")
P("<b>Keep windows running</b> sama dengan " + C("wake auto-on") + ". <b>Model for the wake request</b> berupa "
  "daftar model yang tersedia untuk akun itu, diambil dari provider (daftar yang sama dengan " + C("wake models")
  + "), dengan <b>Default</b> di urutan pertama; di bawahnya tertulis asal daftar dan kapan dibaca. Dialog membaca "
  "daftar itu hanya bila yang tersimpan lebih tua dari 6 jam; selain itu dialog terbuka tanpa request. Model yang "
  "diisi manual dan tidak ada di daftar tetap terpilih, dengan tanda " + C("not in the list") + ". Bila daftar "
  "tidak bisa dibaca, muncul kolom teks untuk mengetik id-nya. <b>Save settings</b> muncul setelah salah satu "
  "pengaturan diubah; <b>Wake N accounts</b> menyimpan model yang diganti lebih dulu, jadi wake memakai model yang "
  "Anda pilih. Tombolnya bertuliskan <b>Wake: auto</b> selama wake otomatis menyala.")
shot("wake", "Dialog Wake: dua akun tanpa jendela berjalan sudah dicentang, kotak pilih semua di kepala tabel, akun "
     "lain dengan jam resetnya, sakelar yang menjaga jendela tetap berjalan, dan daftar model dari provider.", width=0.85)
shot("wake-models", "Daftar model di dialog Wake: Default di urutan pertama, lalu model yang tersedia untuk akun itu.",
     width=0.85)
P("<b>Tombol mata</b> menyensor semua email di halaman (" + C("al•••e@e•••.com") + "). Ini pengaturan yang sama "
  "dengan " + C("privacy on") + ", jadi peringatan dan output perintah ikut tersensor. Klik lagi untuk menampilkannya. "
  "Halaman mengingat pilihan ini, jadi email asli tidak sempat terlihat saat halaman dimuat ulang.")
shot("privacy", "Tab Accounts dengan sensor email menyala: tabel, kartu, dan jadwal hanya menampilkan email yang disamarkan.")
P("<b>rotation: ...</b> di header membuka dialog rotasi: satu pilihan per profil dengan strateginya sekarang, baris "
  "<b>Every profile</b> untuk mengubah semuanya, dan penjelasan tiap strategi. Selama ada profil yang tidak memakai "
  + C("fill_first") + ", dialog menjelaskan kenapa itu bentrok dengan " + C("balance") + ". <b>Save</b> hanya menulis "
  "profil yang Anda ubah, sama dengan " + C("strategy --only") + ". Tombol <b>Use fill_first</b> di banner melakukan hal "
  "yang sama untuk profil yang disebutnya, setelah konfirmasi.")
P("<b>Chip status bar</b> " + C("8/8 · 12%") + " artinya 8 dari 8 akun dalam rotasi bisa dipakai, dan akun tempat "
  "sesi berikutnya mulai ada di 12%. Muncul titik kuning saat ada peringatan aktif, merah saat tidak ada akun yang "
  "bisa dipakai. Chip disembunyikan selama provider belum punya akun atau backend belum dimuat.")
H2("8.4 Tambah akun dan login ulang dari halaman")
OL(["<b>Add account</b>, ketik email akun, <b>Start sign-in</b>. Untuk akun yang sudah ada, pakai tombol kunci di "
    "barisnya (atau <b>Sign in again</b> di banner akun mati); itu sama dengan " + C("relogin") + ".",
    "<b>Anthropic</b>: klik <b>Copy link</b>, buka link itu di browser yang login sebagai akun tersebut (profil "
    "browser sendiri, atau jendela private). Pastikan tertulis " + C("Logged in as ...") + ", authorize, salin kodenya, "
    "tempel di halaman, lalu <b>Finish</b>.",
    "<b>Codex</b> menanyakan cara login: <b>Browser on this computer</b> (default) atau <b>Device code</b>. "
    "<b>Browser</b>: klik <b>Copy link</b>, buka di browser komputer ini yang login ChatGPT sebagai akun itu, pilih "
    "workspace, authorize. Browser mendarat di halaman " + C("localhost:1455") + " bertuliskan <i>authorization "
    "received</i>, dan dialog selesai sendiri sesaat kemudian. Jika browser ada di komputer lain, halaman terakhirnya "
    "tidak terbuka: salin seluruh alamatnya (" + C("http://localhost:1455/auth/callback?code=...") + "), tempel di "
    "dialog, lalu <b>Finish</b>. <b>Device code</b>: buka halaman yang ditampilkan dan masukkan kodenya; dialog "
    "selesai sendiri setelah Anda konfirmasi. Workspace Business dan Enterprise sering mematikan cara ini (bagian 6.4).",
    "Hasilnya sama dengan di terminal: " + C("add") + " hanya menyimpan login jika emailnya cocok dan akun belum ada "
    "di pool, lalu langsung balance; " + C("relogin") + " menukar login lama di posisi yang sama hanya jika akunnya "
    "sama."])
note("Tombol <b>Open in default browser</b> juga ada, tetapi browser default sering login sebagai akun lain. Cara aman: "
     "<b>Copy link</b> lalu buka di profil browser yang benar. Login yang tidak selesai dalam 15 menit kedaluwarsa, "
     "<b>Cancel</b> langsung membatalkannya, dan setiap login hanya bisa diselesaikan sekali.")
shot("add-account", "Add account untuk Anthropic: salin link, buka di browser yang login sebagai akun itu, tempel "
     "kodenya, Finish.", width=0.85)
shot("add-account-codex", "Add account untuk Codex lewat browser: dialog menunggu browser kembali ke localhost:1455; "
     "kolom alamat hanya untuk browser di komputer lain.", width=0.85)
P("<b>Siapa yang menjalankan login.</b> Hermes. Backend halaman menjalankan " + C("hermes auth add &lt;provider&gt; "
  "--type oauth --label &lt;email&gt;") + " (untuk login browser Codex ditambah " + C("--browser --no-browser")
  + ", perintah yang sama dengan " + C("add") + " di terminal), menampilkan link dan kode yang dicetak Hermes, dan "
  "meneruskan yang Anda tempel ke Hermes. Hermes menukar kodenya, menyimpan akun di pool-nya, dan memegang code "
  "verifier; plugin tidak pernah melihat token. Sebelum kode atau alamat yang ditempel sampai ke Hermes, backend "
  "memeriksa bahwa itu milik login ini (" + C("state") + " di link), jadi kode dari login lain mendapat pesan "
  "<i>another sign-in</i>, bukan penukaran yang gagal.")
P("Untuk login browser Codex, Hermes mendengarkan di " + C("127.0.0.1:1455") + ", satu-satunya alamat tujuan OpenAI "
  "mengembalikan browser; alamat yang Anda tempel diteruskan ke situ. Hermes berhenti mendengarkan saat login selesai, "
  "dibatalkan, atau setelah 15 menit. Hanya satu login browser Codex yang menunggu dalam satu waktu: memulai yang "
  "kedua mengakhiri yang pertama. Bila port dipakai program lain (login Codex CLI, atau "
  + C("hermes auth add openai-codex --browser") + " di terminal), Hermes beralih ke kode perangkat, dan dialog "
  "menyebut alasannya. Login yang ditolak OpenAI (Anda menekan <i>Cancel</i> di sana, atau link kedaluwarsa) "
  "membawa dialog kembali ke langkah pertama, email tetap terisi.")
H2("8.5 Permintaan ke provider")
table([
    ["Anda", "Permintaan"],
    ["Membuka halaman, pindah tab, melihat chip", "Tidak ada. Pemakaian dibaca dari riwayat yang ditulis timer tiap "
     "5 menit, token dari pelacak sesi, harga API dari daftar harga Hermes."],
    ["Live usage", "Satu permintaan pemakaian per akun, termasuk akun parkir. Paling sering sekali per 2 menit per "
     "provider; tombolnya menghitung mundur."],
    ["Balance now", "Sama dengan " + C("balance") + ". Paling sering sekali per menit, bersama Check accounts."],
    ["Check accounts", "Satu permintaan profil per akun."],
    ["Wake", "Satu permintaan pemakaian per akun yang dicentang, lalu satu request model kecil per akun yang jendelanya "
     "tidak berjalan. Paling sering sekali per menit, bersama Balance now dan Check accounts."],
    ["Membuka dialog Wake", "Tidak ada, kecuali daftar model yang tersimpan lebih tua dari 6 jam: satu permintaan "
     "daftar model (tanpa kuota). Bacaan yang gagal tidak diulang dalam satu menit."],
    ["Tombol mata, pengaturan wake", "Tidak ada."],
    ["Run doctor", "Satu permintaan pemakaian."],
    ["Add account, Sign in again", "Proses login, lalu satu permintaan profil untuk verifikasi email."],
], [0.34, 0.66])
P("Endpoint pemakaian membatasi permintaan per akun (lihat Troubleshooting), jadi halaman tidak pernah memanggilnya "
  "sendiri.")
H2("8.6 Keamanan halaman")
LI(["Halaman adalah " + C("desktop/plugin.js") + ", sebuah desktop plugin Hermes. Ia hanya mengimpor SDK plugin Hermes "
    "dan React, dan hanya bicara dengan backend-nya sendiri.",
    "Backend-nya " + C("dashboard/plugin_api.py") + ", dipasang Hermes di " + C("/api/plugins/account-pool/")
    + " jika " + C("account-pool") + " ada di " + C("plugins.enabled") + " profil yang sedang dijalankan Desktop. Setiap "
    "permintaan wajib membawa session token desktop.",
    "Jawaban backend hanya berisi label, id, status, persen, dan waktu. Token tidak pernah keluar dari backend. "
    "Login yang sedang berjalan adalah proses " + C("hermes auth add") + " yang diajak bicara backend; PKCE verifier "
    "dan device id-nya tetap di dalam proses Hermes itu.",
    "Halaman selalu memakai pool bersama di Hermes home default, profil mana pun yang sedang dibuka di jendela. Bot "
    "tidak bisa memakainya: ini bagian aplikasi desktop, bukan tool.",
    "Satu aksi berjalan dalam satu waktu; klik kedua saat aksi masih jalan mendapat pesan " + C("Another account action is still running") + "."])

H1("9. Peringatan")
table([
    ["Peringatan", "Kapan", "Dikirim"],
    ["<b>Akun perlu login ulang</b>", "Sebuah akun berstatus DEAD", "Sekali per akun"],
    ["<b>Semua akun di atas 80%</b>", "Setiap akun dalam rotasi ≥ 80% (butuh adapter)", "Sekali, lalu kabar saat pulih"],
    ["<b>Bot jauh di atas biasanya</b>", "Satu jam terakhir sebuah profil ≥ $15 harga API atau ≥ 300 request, dan "
     "3 kali jam biasanya", "Sekali per bot, paling sering tiap 6 jam"],
], [0.30, 0.44, 0.26])
LI(["Peringatan dikirim oleh " + C("balance") + ", jadi butuh timer.",
    "<b>Desktop</b>: " + C("notify-send") + " di Linux, notifikasi Windows di Windows; aktif secara default.",
    "<b>Telegram</b>: aktif otomatis jika Hermes punya bot Telegram. Pesan dikirim lewat " + C("hermes send -t telegram")
    + " milik Hermes, memakai bot profil default, ke <b>home channel</b> bot: chat tempat Anda mengirim "
    + C("/sethome") + " ke bot. Untuk chat lain, sebut id-nya: " + C("notify telegram-to=&lt;id chat&gt;") + " ("
    + C("telegram-to=home") + " kembali ke home channel). Jika bot default belum diatur atau tokennya tidak valid, "
    "pakai bot profil lain: " + C("notify telegram-via=&lt;profil&gt;") + ". Selama bot belum punya home channel, "
    + C("doctor") + ", " + C("notify") + " dan tab Alerts memberi tahu, karena tidak ada yang sampai. Plugin tidak "
    "membaca " + C(".env") + " atau pengaturan Telegram sendiri.",
    "Jalankan " + C("notify test") + " setelah mengatur."])
H2("Peringatan bot boros", need=80)
P("Peringatan ini menangkap loop atau tugas yang lepas kendali sebelum menghabiskan pool:")
code("""
Hermes: worker-1 is using far more than usual
Last hour: $20.00 at API prices, 100 requests, 5.0M tokens, 20x its usual $1.00 per
active hour.
Busiest session: Shipping: admin page for limits (kanban, task t_5f2e91, 100 requests).
Check: hermes account anthropic sessions --hours 1
""")
LI(["<b>Biasanya</b> = rata-rata jam aktif profil itu (jam dengan minimal satu request) dalam 7 hari sebelumnya. "
    "Selama profil belum punya 3 jam aktif, nilai biasanya belum ada dan batas bawahnya dihitung dua kali lipat "
    "($30 atau 600 request).",
    "Kedua syarat harus terpenuhi, jadi bot yang memang selalu sibuk tidak memicu peringatan, dan bot sepi yang "
    "pemakaiannya naik dua kali lipat juga tidak.",
    "Bot yang dekat batas bisa naik-turun melewatinya dari putaran ke putaran. Pesannya paling sering sekali per 6 jam "
    "per bot (" + C("alert_bot.cooldown_h") + "); banner di halaman tetap tampil selama bot di atas batas.",
    "Dihitung dari file pelacak sesi, tanpa permintaan ke provider. Token tanpa nama bot tidak ikut.",
    C("notify bots=25") + " mengubah batas dolar (sekaligus menyalakan), " + C("notify bots-off") + " mematikan. Batas "
    "request, faktor, dan jedanya ada di " + C("alert_bot.requests") + ", " + C("alert_bot.factor") + ", dan "
    + C("alert_bot.cooldown_h") + " di file pengaturan."])
H2("Ringkasan harian", need=70)
P(C("notify daily=08:00") + " mengirim ringkasan 24 jam terakhir sekali sehari, pada putaran timer pertama setelah "
  "jam 08:00, ke saluran yang sama dengan peringatan. Ringkasan dikirim per provider, dan hanya untuk provider yang "
  "punya sesuatu untuk dilaporkan: ada permintaan yang tercatat, pemakaian di atas 0%, atau akun yang perlu login "
  "ulang. Provider yang akunnya diam seharian tidak mengirim ringkasan. Jika dinyalakan setelah jam itu, ringkasan "
  "pertama datang besoknya. " + C("notify summary") + " langsung mengirim satu, sekaligus sebagai pratinjau.")
code("""
Hermes anthropic: last 24 h
Tokens: 10.9M in 647 requests, $5.66 at API list prices.
Bots: worker-1 5.6M, worker-2 2.4M, default 1.9M, worker-3 1.1M.
Share of the load: bob 27%, carol 25%, alice 24% and 1 more. Highest 5-hour
usage: 60% (bob). Every account >= 90% at once: 0 min.
Busiest hour: 08:00-09:00.
Now: 4 in rotation, 0 parked; new sessions start on alice (59%).
""")
P("Akun yang perlu login ulang dan saran dari " + C("report") + " ikut ditambahkan bila ada, juga perkiraan (jika "
  "pool punya beban dalam satu jam terakhir) dan sesi dengan harga API tertinggi. Ringkasan dibuat dari "
  "file plugin sendiri, tanpa permintaan ke provider. " + C("notify daily-off") + " mematikannya.")
H2("File pengaturan", need=50)
P("Pengaturan disimpan di " + C("$HERMES_HOME/account-pool.json") + " (dibuat saat perubahan pertama). File ini "
  "juga boleh diedit; ambang peringatan ada di " + C("alert_all_above") + ", jam ringkasan harian di "
  + C("notify.daily") + ", peringatan bot di " + C("alert_bot") + " (" + C("usd") + " dan " + C("requests")
  + " per jam, " + C("factor") + " terhadap jam biasanya, " + C("cooldown_h") + " jeda antarpesan untuk bot yang sama), "
  "jadwal parkir di " + C("schedules") + ", wake otomatis dan modelnya per provider di " + C("wake")
  + ", dan sensor email di " + C("mask_emails") + ":")
code("""
{"notify": {"desktop": true, "telegram": "auto", "telegram_via": "default", "daily": "08:00"},
 "alert_all_above": 80,
 "alert_bot": {"on": true, "usd": 15, "requests": 300, "factor": 3, "cooldown_h": 6},
 "schedules": {"anthropic": [{"label": "dave@example.com", "id": "a3b2c3",
                              "days": [0, 1, 2, 3, 4], "from": "09:00", "to": "17:00"}]},
 "wake": {"anthropic": {"auto": true}, "openai-codex": {"auto": false, "model": "gpt-6-luna"}},
 "mask_emails": true}
""")
H2("Perkiraan: kapan semua akun penuh", need=70)
P(C("usage") + ", " + C("report") + ", ringkasan harian, dan halaman Accounts menyebut kapan semua akun ≥ 90% jika "
  "pool terus dipakai dengan laju satu jam terakhir:")
code("""
Forecast: At the last hour's pace (31% of one 5-hour window per hour), every account is at
90% or more around 16:40, until about 17:20 when the first one resets.
""")
LI(["Lajunya adalah jumlah kenaikan pemakaian semua akun dalam satu jam terakhir, dari riwayat timer. Tidak ada "
    "permintaan ke provider.",
    "Perkiraan membagikan laju itu menit demi menit ke akun paling longgar di bawah 90%, seperti " + C("balance")
    + " dan " + C("fill_first") + " membagi sesi baru, dan mengembalikan ruang akun saat jendelanya reset. Jangkauannya "
    "satu panjang jendela (5 jam untuk Anthropic).",
    "Asumsinya akun berpaket sama (persennya bisa dijumlah) dan beban stabil; bot yang mulai atau berhenti mengubahnya "
    "dalam satu jam. Baca sebagai \"dengan laju ini\", bukan janji.",
    "Dengan riwayat baru kurang dari 25 menit, atau tanpa akun yang pemakaiannya diketahui, tidak ada perkiraan. Tanpa "
    "beban dalam satu jam terakhir, perkiraan menyebutnya."])

H1("10. Cara kerja balance")
P("Setiap putaran, untuk satu provider:")
OL(["<b>Park bertanggal</b>: mengaktifkan lagi akun yang waktu " + C("--until") + "-nya sudah lewat (termasuk "
    "jendela jadwal yang sudah berakhir).",
    "<b>Jadwal</b>: memarkir akun yang jendela jadwalnya sudah mulai, sampai jendela itu berakhir.",
    "<b>Parkir diselaraskan dengan Hermes</b>: memarkir lagi akun yang dikembalikan Hermes ke rotasi sebelum "
    "waktunya, memperpanjang tahanan 30 hari parkir tanpa jam selesai begitu sisanya kurang dari 15 hari, melupakan parkir akun yang sudah keluar "
    "dari pool, dan mengembalikan akun yang ditahan Hermes sebagai parkir padahal tidak ada di daftar parkir.",
    "<b>Pemulihan</b>: mencoba ulang refresh token akun yang COOLING DOWN.",
    "<b>Pemakaian</b> (butuh adapter): membaca pemakaian semua akun; Hermes me-refresh access token yang "
    "kedaluwarsa dulu.",
    "<b>Istirahat dan lepas</b>: akun ≥ ambang diistirahatkan sampai jendelanya reset (ditandai "
    + C("[account-pool]") + "); akun yang sudah turun dilepas. Limit asli dari provider tidak pernah disentuh.",
    "<b>Urutan</b>: pemakaian terendah dulu, lalu akun yang diistirahatkan, lalu akun yang pemakaiannya tidak "
    "terbaca, lalu akun DEAD.",
    "<b>Wake</b> (hanya dengan " + C("wake auto-on") + "): satu request kecil lewat setiap akun dalam rotasi yang "
    "jendela 5 jamnya tidak berjalan, dari pemakaian yang dibaca di langkah 5 (bagian 7.16).",
    "<b>Riwayat</b>: satu snapshot per putaran untuk " + C("report") + " dan cadangan \"last known\". Nilai yang "
    "berasal dari cadangan itu tidak pernah ditulis ulang.",
    "<b>Peringatan</b> untuk masalah baru (akun perlu login ulang, semua akun tinggi, bot jauh di atas biasanya), "
    "dan ringkasan harian bila sudah waktunya.",
    "<b>Log aktivitas</b>: setiap perubahan dari langkah 1 sampai 10 dicatat di " + C("account-pool-activity.jsonl")
    + " (lihat " + C("log") + ", 7.14)."])
note("<b>Pengaman.</b> Jika <b>semua</b> akun ≥ ambang, hanya akun yang 100% yang diistirahatkan, jadi pool tidak "
     "pernah dikosongkan karena \"hampir penuh\". Jika pemakaian tidak terbaca sama sekali, urutan tidak diubah; "
     "pemulihan, unpark terjadwal, jadwal parkir, peringatan, dan ringkasan harian tetap jalan. Sesi yang sedang berjalan tidak dipindah, karena "
     "pindah akun membuang prompt cache.")
H2("Pindah akun otomatis bawaan Hermes")
table([
    ["Kondisi dari provider", "Tindakan Hermes", "Akun diistirahatkan"],
    ["429 rate limit", "Coba ulang 1x (menunggu sampai 600 detik), lalu pindah. Langsung pindah jika akun "
     "sudah berstatus limit/benched", "Sampai reset, atau 1 jam"],
    ["\"usage limit reached\"", "Langsung pindah", "Sampai reset"],
    ["402 / billing", "Langsung pindah", "1 jam"],
    ["401 token kedaluwarsa", "Refresh token, tidak pindah", "5 menit jika refresh gagal"],
    ["Refresh token ditolak", "Akun DEAD, keluar dari rotasi", "Sampai login ulang"],
], [0.25, 0.47, 0.28])
P("Ambang 90% membuat akun diistirahatkan sebelum penuh, sehingga sesi baru tidak macet menunggu 600 detik.")

H1("11. Timer otomatis")
P(C("hermes account &lt;provider&gt; setup --timer") + " memasangnya; " + C("doctor") + " dan halaman Accounts "
  "menampilkan status, putaran terakhir, dan putaran berikutnya di kedua sistem.")
H2("11.1 Linux (systemd)")
code("""
hermes account anthropic setup --timer                             # pasang (semua provider)
hermes account all balance                                         # yang dijalankan timer
hermes account openai-codex setup --undo                           # keluarkan satu provider
systemctl --user list-timers hermes-account-balance.timer          # status, jadwal berikutnya
journalctl --user -u hermes-account-balance.service -n 20 -o cat   # log
systemctl --user start hermes-account-balance.service              # jalankan sekarang
systemctl --user disable --now hermes-account-balance.timer        # matikan
systemctl --user enable --now hermes-account-balance.timer         # nyalakan
""")
LI(["<b>Interval</b>: " + C("systemctl --user edit --full hermes-account-balance.timer") + ", ubah "
    + C("OnUnitActiveSec=5min") + ". Setiap putaran membaca pemakaian semua akun sekali, jadi jangan jauh di bawah 5 menit.",
    "<b>Ambang</b>: " + C("systemctl --user edit --full hermes-account-balance.service") + ", tambahkan "
    + C("--threshold 85") + " di baris " + C("ExecStart") + ".",
    "<b>Provider</b>: timer menjalankan " + C("hermes account all balance") + ", jadi setiap provider yang punya "
    "akun ikut diseimbangkan, termasuk provider yang baru mendapat akun pertamanya nanti. Pada unit dari 3.10.2 atau "
    "lebih lama (satu baris " + C("ExecStart") + " per provider), " + C("doctor") + " memperingatkan provider "
    "berakun yang terlewat; " + C("hermes account &lt;provider&gt; setup --timer") + " mengubah unit itu ke "
    + C("all") + ".",
    "<b>Hanya sebagian provider</b>: ganti baris " + C("all") + " dengan satu baris per provider ("
    + C("ExecStart=... account anthropic balance") + "), atau jalankan " + C("hermes account &lt;provider&gt; setup --undo")
    + " untuk provider yang mau dikeluarkan.",
    "Timer hanya dipasang jika Anda minta (" + C("setup --timer") + ", atau " + C("install.sh") + " tanpa "
    + C("--no-timer") + "). File unit ditulis oleh " + C("setup") + ", bukan diambil dari template.",
    "Timer tidak memakai token AI kecuali wake otomatis dinyalakan (" + C("wake auto-on") + "): ia memanggil endpoint "
    "pemakaian dan, untuk peringatan dan ringkasan harian, saluran notifikasi Anda. Dengan wake otomatis, ia juga "
    "mengirim satu request model kecil saat jendela suatu akun tidak berjalan."])
H2("11.2 Windows (Task Scheduler)", need=60)
code("""
schtasks /Query /TN "Hermes Account Balance" /V /FO LIST   # status, putaran terakhir
Get-Content "$env:LOCALAPPDATA\\hermes\\account-pool-timer\\balance.log" -Tail 20
schtasks /Run /TN "Hermes Account Balance"                 # jalankan sekarang
schtasks /Change /TN "Hermes Account Balance" /DISABLE     # matikan
schtasks /Change /TN "Hermes Account Balance" /ENABLE      # nyalakan
""")
P("Task menjalankan " + C("wscript.exe balance.vbs") + ", yang menjalankan " + C("balance.cmd") + " tanpa jendela, "
  "jadi tidak ada jendela yang berkedip tiap 5 menit. Kedua file ada di "
  + C("%LOCALAPPDATA%\\hermes\\account-pool-timer\\") + " (di bawah " + C("HERMES_HOME") + " jika Anda mengaturnya).")
LI(["<b>Kapan jalan</b>: tiap 5 menit selama Anda login ke Windows, juga saat memakai baterai. Setelah komputer "
    "mati atau tidur, putaran yang terlewat langsung dikejar. Tidak pernah dua putaran sekaligus, dan satu putaran "
    "dihentikan setelah 10 menit.",
    "<b>Ambang</b>: tambahkan " + C("--threshold 85") + " di baris " + C("account all balance") + " dalam "
    + C("balance.cmd") + ". " + C("setup") + " mempertahankan opsi yang Anda tambahkan, sama seperti di Linux.",
    "<b>Interval</b>: buka Task Scheduler (" + C("taskschd.msc") + "), task <b>Hermes Account Balance</b>, tab "
    "Triggers, lalu ubah <i>Repeat task every</i>. Jangan jauh di bawah 5 menit.",
    "<b>Hanya sebagian provider</b>: ganti baris " + C("all") + " di " + C("balance.cmd") + " dengan satu baris per "
    "provider, atau jalankan " + C("hermes account &lt;provider&gt; setup --undo") + " untuk provider yang mau dikeluarkan.",
    "<b>Hapus</b>: " + C("setup --undo") + " untuk provider terakhir menghapus task dan filenya; " + C("uninstall.ps1")
    + " juga.",
    "<b>Log</b>: setiap putaran ditambahkan ke " + C("balance.log") + "; di 1 MB file itu dipindah ke "
    + C("balance.log.1") + ". " + C("last-run.json") + " di sebelahnya menyimpan mulai, selesai, dan exit code "
    "putaran terakhir, yang dibaca " + C("doctor") + " dan halaman."])

H1("12. Provider dan Codex")
table([
    ["Fitur", "Provider"],
    [C("list") + ", " + C("check") + ", " + C("add") + "/" + C("remove") + ", " + C("park") + "/" + C("unpark")
     + " (+ " + C("--until") + "), " + C("schedule") + ", " + C("who") + ", token dan harga API, " + C("doctor")
     + ", peringatan login, ringkasan harian, pemulihan cooling down",
     "<b>Semua provider</b> di credential pool (OAuth dan API key)"],
    [C("relogin"), "Provider dengan login OAuth. Verifikasi email butuh adapter identity."],
    [C("usage") + ", " + C("report") + ", urutan " + C("balance") + ", " + C("wake") + ", peringatan \"semua akun tinggi\", email asli",
     "Provider yang punya <b>adapter</b>. Bawaan: <b>anthropic</b> (5 jam) dan <b>openai-codex</b> (5 jam + mingguan)."],
], [0.55, 0.45])
LI(["Tanpa adapter, " + C("usage") + " dan " + C("report") + " menampilkan pesan jelas, dan " + C("balance")
    + " tetap menjalankan unpark terjadwal, pemulihan, dan peringatan login, tetapi urutan akun tidak diubah.",
    "<b>Codex</b>: balance memakai limit yang paling ketat di antara 5 jam dan mingguan, dan " + C("usage")
    + " menampilkan keduanya, misalnya " + C("5h 12% · week 78%") + ". Akun Codex yang juga login di Codex CLI atau "
    "VS Code berbagi kuota dengan aplikasi itu. Hermes memakai login Codex-nya sendiri dan tidak mengambil "
    + C("~/.codex/auth.json") + ".",
    "Provider lain bisa ditambahkan dengan menulis satu adapter (lihat CONTRIBUTING.md di repo)."])
note("Plugin hanya mengelola akun <b>di dalam</b> satu provider. Apakah sebuah profil memakai provider itu (model utama, "
     "urutan fallback) tetap diatur di pengaturan Hermes, dan plugin tidak pernah mengubahnya. Provider yang belum "
     "punya akun cukup diam: " + C("hermes account openai-codex doctor") + " menyebutnya \"not in use\".")

H1("13. File dan keamanan")
table([
    ["File", "Isi"],
    [C("~/.hermes/plugins/account-pool/"), "Plugin (perintah " + C("hermes account") + "), adapter di "
     + C("providers.py") + ", pelacak sesi di " + C("tracker.py") + " (mencatat juga versinya, id proses, dan tugas "
     "Kanban), login dari halaman di " + C("signin.py") + ". Perintahnya hanya terdaftar di profil default; di "
     "profil lain (lewat symlink di " + C("profiles/*/plugins/") + ") hanya pelacak sesi."],
    [C("~/.hermes/plugins/account-pool/desktop/"), "Halaman Accounts untuk Hermes Desktop. Desktop menyalinnya ke "
     + C("~/.hermes/desktop-plugins/account-pool/") + "."],
    [C("~/.hermes/plugins/account-pool/dashboard/"), "Backend halaman (" + C("plugin_api.py") + ") dan manifest-nya."],
    [C("~/.hermes/auth.json"), "Credential pool bersama semua profil (milik Hermes)"],
    [C("~/.hermes/account-pool-parking.json"), "Daftar parkir: label, id pool, kapan diparkir dan sampai kapan. "
     "Tanpa token: loginnya tetap di pool Hermes. (3.x memakai " + C("account-pool-parked.json") + " berisi login; "
     "4.0 memindahkannya ke pool sekali lalu menghapusnya.)"],
    [C("~/.hermes/account-pool-sessions.json"), "Sesi dan akunnya, 24 jam terakhir (tanpa token)"],
    [C("~/.hermes/account-pool-tokens.json"), "Jumlah token per akun, profil, dan model, serta per profil, sesi, dan "
     "model, dalam blok 15 menit, 8 hari terakhir. Hanya angka dan id sesi."],
    [C("~/.hermes/account-pool-activity.jsonl"), "Log aktivitas: apa yang diubah timer, perintah, dan halaman. 30 hari "
     "terakhir, izin 600."],
    [C("~/.hermes/account-pool-history.jsonl"), "Riwayat pemakaian, satu snapshot per putaran timer. Akun parkir "
     "ikut dicatat dan ditandai " + C("parked") + "; laporan, perkiraan, grafik, dan ringkasan harian tidak "
     "menghitungnya. Dipangkas ke 14 hari terakhir saat file melewati 3 MB."],
    [C("~/.hermes/account-pool-alerts.json"), "Peringatan yang sudah terkirim (satu pesan per kejadian)"],
    [C("~/.hermes/account-pool-state.json"), "Kapan ringkasan harian terakhir dikirim, jendela jadwal yang sudah "
     "dijalankan, wake terakhir tiap akun (waktu, model, atau alasan gagal), dan daftar model terakhir per "
     "provider (waktu dan id)"],
    [C("~/.hermes/account-pool.json"), "Pengaturan: saluran peringatan, ringkasan harian, peringatan bot, jadwal "
     "parkir, wake, sensor email"],
    [C("~/.config/systemd/user/") + "<br/>" + C("hermes-account-balance.{service,timer}"), "Linux: timer 5 menit, "
     "ditulis " + C("setup --timer")],
    [C("account-pool-timer\\") + "<br/>" + C("balance.cmd, balance.vbs, balance.log, last-run.json"),
     "Windows: file timer di folder Hermes, ditulis " + C("setup --timer") + "; task-nya <b>Hermes Account Balance</b> "
     "di Task Scheduler"],
], [0.48, 0.52])
P("Di Windows folder Hermes adalah " + C("%LOCALAPPDATA%\\hermes") + " (bukan " + C("~/.hermes") + "), dan file "
  "data mewarisi izin folder user Anda, yang hanya bisa dibaca Anda dan administrator.")
P("Cara token diperlakukan:")
LI(["Plugin tidak menyimpan token. Login ada di pool Hermes (" + C("auth.json") + "), dan plugin menjangkaunya "
    "lewat API pool Hermes. Semua file data berizin 600 (di Linux).",
    "Token tidak pernah dicetak atau dicatat di log. Plugin hanya memasukkan access token akun ke header permintaan "
    "ke endpoint pemakaian, profil, daftar model, dan (untuk " + C("wake") + ") model milik provider itu sendiri.",
    "Refresh token dan login milik Hermes sendiri: " + C("try_refresh_matching") + " untuk token yang kedaluwarsa, "
    + C("hermes auth add") + " untuk login. Hermes yang menyimpan hasilnya.",
    "Untuk peringatan dan ringkasan harian plugin menghubungi Telegram lewat " + C("hermes send") + " milik Hermes. "
    "Tidak ada tujuan lain. Harga API diambil dari file yang sudah dimiliki Hermes.",
    "Halaman Accounts tidak menerima token: backend-nya hanya mengirim label, id, status, dan angka.",
    "API key untuk " + C("add --key") + " dibaca tanpa ditampilkan di dalam plugin dan diserahkan ke "
    + C("auth_add_command") + " milik Hermes, tidak pernah lewat command line.",
    "Plugin utama hanya di profil default, jadi profil bot tidak bisa mengubah akun."])
H2("Pengungkapan keamanan dan privasi", need=60)
P("Ringkasan semua yang dilakukan plugin di luar file miliknya sendiri: yang perlu Anda ketahui sebelum "
  "menjalankannya. Isinya mengikuti pengungkapan yang diminta aturan katalog plugin Hermes (aturan 13; lihat "
  "bagian 4.2). Versi lengkapnya, termasuk daftar "
  "fungsi internal Hermes yang dipakai, ada di README bagian <i>Security and privacy disclosure</i>.")
table([
    ["Hal", "Rincian"],
    ["Mengubah credential pool, tanpa memegang login sendiri", C("add") + ", " + C("relogin") + ", " + C("remove") + ", " + C("park") + ", " + C("unpark")
     + ", " + C("schedule") + ", dan " + C("balance") + " mengubah pool lewat API " + C("CredentialPool") + " milik "
     "Hermes (" + C("load_pool") + ", " + C("remove_index") + ", " + C("mark_exhausted_and_rotate") + ", "
     + C("reset_status") + ", " + C("try_refresh_matching") + ") atau " + C("hermes auth add/remove") + ". Tidak ada "
     "yang mengedit atau membaca " + C("auth.json") + " langsung; akun profil lain dibaca lewat "
     + C("read_credential_pool") + ". " + C("park") + " membiarkan akun di pool dan meminta Hermes melewatinya "
     "(alasan " + C("parked") + ", waktu reset); " + C("unpark") + " = " + C("reset_status") + ". Daftar parkir hanya "
     "berisi label, id, dan waktu. Login dari terminal dan dari halaman sama-sama " + C("hermes auth add") + " milik "
     "Hermes; PKCE verifier, device id, dan token tetap di dalam Hermes."],
    ["Request model", "Hanya untuk " + C("wake") + ": satu request dengan jawaban satu kata per wake. Anthropic "
     "lewat klien Hermes sendiri (" + C("build_anthropic_client") + ", identitas Claude Code yang dikirim Hermes di "
     "setiap request langganan); Codex lewat endpoint Responses dengan header " + C("codex_cli_rs") + ". Jalan saat "
     "Anda menjalankan " + C("wake") + ", menekan <b>Wake</b>, atau dari timer setelah " + C("wake auto-on")
     + ". Tidak ada bagian lain dari plugin yang memanggil model."],
    ["Listener lokal", "Tidak ada milik plugin. Selama login Codex lewat browser, " + C("hermes auth add --browser")
     + " milik Hermes mendengarkan di " + C("127.0.0.1:1455") + " (loopback), sama seperti di terminal."],
    ["Jaringan", C("api.anthropic.com") + " (usage, profile), " + C("chatgpt.com/backend-api/wham/usage")
     + ", untuk wake "
     + C("api.anthropic.com/v1/messages") + " dan " + C("chatgpt.com/backend-api/codex/responses") + ", daftar "
     "model untuk wake (" + C("api.anthropic.com/v1/models") + " lewat fungsi Hermes, daftar model Codex), dan Telegram "
     "lewat " + C("hermes send") + ". Header klien sama dengan "
     "pembaca pemakaian Hermes (" + C("claude-code/2.1.0") + ", " + C("codex_cli_rs") + "). Login ("
     + C("claude.ai") + ", " + C("auth.openai.com") + ") dan refresh token adalah permintaan Hermes sendiri. Tanpa "
     "telemetri, tanpa cek update."],
    ["Kerja di latar belakang", "Hanya timer, jika dipasang (unit systemd di Linux, task Task Scheduler di "
     "Windows): " + C("all balance") + " tiap 5 menit, untuk semua "
     "provider yang punya akun; dengan " + C("wake auto-on") + " juga wake untuk akun yang jendelanya tidak berjalan "
     "(paling banyak sekitar 5 request kecil per akun per hari). Pelacak sesi berjalan "
     "di dalam setiap proses Hermes yang memuat plugin, sebagai hook " + C("post_api_request") + "; ia hanya menulis "
     "file sesi dan token."],
    ["Perintah yang dijalankan", C("systemctl --user") + " dan " + C("notify-send") + " (Linux), " + C("schtasks")
     + " dan " + C("powershell.exe") + " untuk notifikasi (Windows), " + C("hermes config set")
     + " (cadangan bila penulis config Hermes tidak bisa diimpor), " + C("hermes plugins remove account-pool-tracker")
     + " (sekali, update dari 3.x), " + C("hermes auth add") + " (terminal dan halaman), " + C("taskkill")
     + " (Windows: login halaman yang dibatalkan), " + C("hermes auth remove") + ", " + C("hermes send -t telegram") + "."],
    ["Dibaca di luar file sendiri", C("config.yaml") + " dan " + C("state.db") + " (read-only) setiap profil, "
     + C("/proc/self/cgroup") + " di Linux (apakah proses ini service timer; di Windows " + C("balance.cmd")
     + " memberi tanda lewat variabel lingkungan), pengaturan gateway Hermes (apakah bot Telegram punya home "
     "channel; tanpa membaca token), command line proses Hermes (" + C("doctor") + "; "
     + C("/proc/&lt;pid&gt;/cmdline") + " di Linux, " + C("psutil") + " di Windows), file harga Hermes, status "
     "unit systemd atau task Task Scheduler."],
    ["Ditulis di luar file sendiri", "Credential pool, lewat Hermes, seperti di atas; " + C("config.yaml")
     + " profil hanya lewat penulis config Hermes (atau " + C("hermes config set") + ") dari " + C("setup") + ", "
     + C("strategy") + ", dan dialog rotasi; symlink (atau junction di Windows) plugin di " + C("profiles/*/plugins/") + "; unit "
     "systemd di Linux, task Task Scheduler dan " + C("account-pool-timer\\") + " di Windows."],
], [0.24, 0.76])

H1("14. Memaksa akun tertentu")
code("""
# Cara 1: parkir akun yang tidak ingin dipakai (bisa sementara)
hermes account anthropic park frank@example.com --until 17:00
# Cara 1b: parkir di jam yang sama setiap minggu
hermes account anthropic schedule frank@example.com --every "mon-fri 09:00-17:00"

# Cara 2: matikan balance, atur urutan manual, nyalakan lagi nanti
systemctl --user disable --now hermes-account-balance.timer
hermes auth priority anthropic bob@example.com 0
systemctl --user enable --now hermes-account-balance.timer
""")
P("Di Windows, Cara 2 memakai " + C("schtasks /Change /TN \"Hermes Account Balance\" /DISABLE") + " dan "
  + C("/ENABLE") + ".")

H1("15. Troubleshooting")
table([
    ["Gejala", "Penyebab umum", "Solusi"],
    [C("usage") + ": n/a (rate-limited) atau \"last known\"", "Endpoint pengukur pemakaian dipanggil sangat sering "
     "(oleh plugin, aplikasi pemantau lain, atau model picker Hermes Desktop). Ini bukan kuota model Anda.",
     "Tunggu beberapa menit. Bot tidak terpengaruh; balance menaruh akun tanpa data di belakang"],
    [C("setup") + "/" + C("doctor") + ": " + C("No module named 'yaml'"), "Plugin 3.12.0 atau lebih lama di Hermes "
     "0.21.6 ke atas, yang tidak lagi memasang PyYAML", C("hermes plugins update account-pool") + " (3.12.1), lalu "
     + C("setup") + " lagi"],
    ["Login: \"Sign in again to continue\"", "Login di browser sudah lama (kebijakan Anthropic)", "Klik, login ulang sebagai akun yang sama"],
    [C("add") + ": discarded", "Browser login sebagai akun lain, atau akun yang sudah ada di pool",
     "Pakai profil Chrome akun itu atau jendela private baru, lalu " + C("add") + " lagi"],
    [C("Cancelled (Ctrl+C). Nothing was added."), "Ctrl+C saat login", "Memang begitu. Jalankan " + C("add") + " lagi saat siap"],
    ["Bot \"retrying in 600s\"", "Akun kena 429 sebelum balance mengistirahatkannya",
     C("hermes account anthropic balance") + ", lalu stop dan kirim ulang pesan"],
    ["check: DEAD", "Login dicabut atau token dipakai aplikasi/perangkat lain", C("hermes account anthropic relogin &lt;email&gt;")],
    ["check: WRONG LABEL / DUPLICATE", "Ditambah lewat " + C("hermes auth add") + " saat browser login akun lain",
     C("relogin") + " akun yang benar, atau " + C("remove &lt;id&gt;") + " entri lebihnya"],
    [C("who") + " kosong", "Sesi dimulai sebelum plugin dipasang, atau Hermes memakai " + C("plugins.isolation: host"),
     C("/reset") + " sesi, atau restart gateway/desktop. Dengan isolasi " + C("host") + " pelacak tidak bisa melihat "
     "akunnya (bagian 17)"],
    [C("sessions") + " kosong", "Bot masih memakai " + C("account-pool-tracker") + " lebih lama dari 1.5.0", C("hermes gateway restart") + ", restart "
     "Hermes Desktop; " + C("doctor") + " menyebut prosesnya"],
    [C("doctor") + ": session tracker ... is not loaded yet", "Gateway, Hermes Desktop, atau sesi panjang dimulai sebelum "
     "pelacak di-update", C("hermes gateway restart") + "; restart Hermes Desktop; sesi berganti saat selesai"],
    ["Tidak ada pesan Telegram", "Bot belum punya home channel, atau token bot profil pengirim tidak valid",
     "Kirim " + C("/sethome") + " ke bot di chat yang harus menerima peringatan, atau " + C("notify telegram-to=&lt;id chat&gt;")
     + "; lalu " + C("notify test") + ". Bot rusak: ganti " + C("telegram-via")],
    [C("report") + ": not enough history", "Timer mati atau baru dipasang", C("doctor") + ", tunggu beberapa putaran"],
    ["Peringatan bot terlalu sering", "Batas bawah terlalu rendah untuk beban Anda", C("notify bots=30") + " (atau "
     + C("bots-off") + "); lihat " + C("sessions --hours 1") + " dulu"],
    ["Akun " + C("--until") + " tidak kembali", "Timer mati", C("hermes account &lt;provider&gt;") + "<br/>" + C("setup --timer")],
    ["Akun parkir tanpa jam reset, garis trennya datar", "Sebelum 3.11.1 timer tidak membaca akun parkir. Di "
     "3.11.1 putaran timer berikutnya mengisinya. Garis datar di 0% dengan " + C("not started") + " berarti "
     "jendelanya sudah habis; arahkan kursor ke garis untuk angka tertinggi 24 jam terakhir",
     "Tunggu putaran timer berikutnya (5 menit) atau tekan <b>Live usage</b>"],
    ["Jadwal tidak memarkir akunnya", "Timer mati, akun itu akun aktif terakhir, atau Anda meng-unpark di tengah jendela",
     C("hermes account anthropic schedule") + " menampilkan keadaan tiap jadwal"],
    ["Ringkasan harian tidak datang", "Timer mati, tidak ada saluran aktif, dinyalakan setelah jamnya hari ini, atau "
     "provider itu tidak punya apa pun untuk dilaporkan", C("notify") + " menampilkan jam dan hari terakhir terkirim; "
     + C("notify summary") + " menguji pengiriman"],
    [C("doctor") + ": " + C("the balance timer does not run openai-codex"), "Unit timer dari 3.10.2 atau lebih lama, "
     "satu baris per provider", C("hermes account openai-codex setup --timer") + " (mengubahnya ke semua provider "
     "yang punya akun)"],
    [C("report") + ": API $ " + C("-") + " atau berakhiran " + C("+"), "Model tanpa harga di daftar Hermes, atau token "
     "dari sebelum pelacak 1.3.0", "Tidak perlu diperbaiki; token itu tidak dihargai"],
    ["doctor: strategy is not fill_first", "Profil memakai " + C("round_robin") + " atau strategi lain",
     C("hermes account &lt;provider&gt;") + "<br/>" + C("strategy fill_first") + ", atau <b>Use fill_first</b> di halaman"],
    ["doctor: profiles with their OWN pool", "Pernah menjalankan " + C("hermes -p &lt;profil&gt; auth add"),
     "Hapus entri di profil itu, lalu tambah akun dari profil default"],
    ["doctor: last run failed", C("balance") + " terakhir gagal", "Linux: " + C("journalctl --user -u") + "<br/>"
     + C("hermes-account-balance.service -n 20") + ". Windows: bagian akhir " + C("balance.log") + " di "
     + C("%LOCALAPPDATA%\\hermes\\account-pool-timer\\")],
    ["Windows, doctor: putaran terakhir timer sudah lama", "Task Scheduler hanya menjalankan task selama Anda login, "
     "jadi wajar setelah komputer mati atau logout", "Tidak perlu apa-apa jika Anda memang pergi; timer jalan lagi "
     "dalam 5 menit setelah login. Selain itu lihat " + C("balance.log") + " dan riwayat task <b>Hermes Account "
     "Balance</b> di Task Scheduler"],
    ["Windows, setup: " + C("Task Scheduler refused the task"), "Kebijakan kantor memblokir scheduled task untuk "
     "user biasa", "Minta bantuan administrator, atau jalankan " + C("hermes account all balance") + " sendiri sesekali"],
    ["Windows: " + C("install.ps1 cannot be loaded because running scripts is disabled"), "Windows memblokir skrip "
     "unduhan secara default", "Jalankan dengan " + C("powershell -ExecutionPolicy Bypass -File .\\install.ps1")
     + " (hanya sekali jalan itu)"],
    ["Windows: notifikasi desktop tidak muncul", "Notifikasi untuk Windows PowerShell dimatikan, atau Focus / Do not "
     "disturb menyala", "Settings &gt; System &gt; Notifications, izinkan Windows PowerShell; lalu "
     + C("hermes account &lt;provider&gt; notify test")],
    [C("hermes account") + " tidak dikenal", "Dijalankan dengan -p (plugin hanya di default)", "Jalankan tanpa -p"],
    ["Halaman: " + C("The account-pool backend did not answer"), "Desktop memakai profil yang belum mencantumkan "
     + C("account-pool") + " (profil baru, atau instalasi sebelum 3.5.1), atau belum di-restart setelah instalasi",
     C("hermes account &lt;provider&gt; setup") + ", lalu restart Hermes Desktop. " + C("doctor") + " menyebut profil yang belum"],
    [C("add needs a terminal") + " / " + C("relogin needs a terminal"), "Dijalankan dari cron, shell agent, atau tempat "
     "lain tanpa terminal, jadi tidak ada yang bisa menempel kode login", "Jalankan di terminal, atau pakai <b>Add "
     "account</b> / <b>Sign in again</b> di halaman"],
    [C("no terminal to answer, so no"), "Perintah yang bertanya dijalankan tanpa terminal", "Jalankan di terminal, "
     "atau tambah " + C("--yes")],
    [C("doctor") + ": " + C("the retired account-pool-tracker plugin is still in: ..."), "Update ke 4.0 belum "
     "diikuti " + C("setup"), C("hermes account &lt;provider&gt; setup")],
    [C("doctor") + ": " + C("parked, but Hermes has them in rotation again"), C("hermes auth reset") + ", atau Hermes "
     "melihat kuota Codex kembali", C("hermes account &lt;provider&gt; balance") + " memarkirnya lagi; timer "
     "melakukannya dalam 5 menit"],
    [C("doctor") + ": " + C("parked accounts that are no longer in the pool"), "Akun dihapus (" + C("hermes auth remove")
     + ") saat diparkir", "Tidak perlu: putaran balance berikutnya melupakan parkirnya"],
    [C("doctor") + ": " + C("held as parked in Hermes, but not parked here"), "Daftar parkir terhapus atau dipulihkan "
     "dari salinan lama", C("hermes account &lt;provider&gt; balance") + " mengembalikannya ke rotasi; " + C("park")
     + " lagi bila ingin dikeluarkan"],
    [C("doctor") + ": " + C("parked without an end time while the balance timer is off"), "Hermes menahan parkir tanpa "
     + C("--until") + " selama 30 hari; hanya putaran balance yang memperpanjangnya", C("hermes account &lt;provider&gt; setup --timer")],
    [C("doctor") + ": " + C("Telegram alerts go to the bot's home channel, but it has none"), "Hermes mengirim ke home "
     "channel bot, dan belum ada", "Kirim " + C("/sethome") + " ke bot di chat yang harus menerima peringatan, atau "
     + C("notify telegram-to=&lt;id chat&gt;")],
    ["Tidak ada Accounts di sidebar", "Bagian Desktop plugin masih mati", "Capabilities &gt; Plugins, account-pool, "
     "nyalakan Desktop. Setelah update: Ctrl+K, " + C("Reload desktop plugins")],
    ["Tombol Live usage abu-abu", "Live usage baru jalan kurang dari 2 menit lalu", "Tunggu hitungan mundurnya"],
    ["Login di halaman: " + C("This code belongs to another sign-in"), "Kode berasal dari link login lain, atau "
     "disalin tanpa bagian setelah " + C("#"), "Buka lagi link dari jendela ini dan salin kode lengkapnya"],
    ["Codex: <i>Please contact your workspace admin to enable device code authentication</i>, <b>Continue</b> "
     "abu-abu", "Workspace ChatGPT mematikan login dengan kode perangkat", "Login tanpa " + C("--device")
     + " (default), atau pilih <b>Browser on this computer</b> di halaman. Atau minta owner menyalakan <i>Enable "
     "device code sign-in for Codex</i>; bisa butuh waktu sebelum berlaku"],
    ["Codex: browser berakhir di halaman " + C("localhost:1455") + " yang tidak terbuka", "Browser ada di komputer "
     "lain, atau login di Hermes sudah berakhir", "Halaman: tempel seluruh alamat itu di dialog. Terminal: pakai "
     "halaman, " + C("--device") + ", atau tunnel SSH yang ditampilkan Hermes"],
    ["Login Codex di halaman: " + C("Port 1455 on this computer is taken ..., so Hermes signs in with a code instead"),
     "Login Codex CLI atau " + C("hermes auth add openai-codex --browser") + " sedang menunggu di port itu",
     "Masukkan kodenya di halaman OpenAI, atau batalkan, selesaikan atau hentikan login yang lain, lalu mulai lagi"],
    ["Codex: " + C("OpenAI refused the sign-in") + " atau " + C("Token exchange failed"), "Anda membatalkan di "
     "halaman OpenAI, atau link sudah lebih dari beberapa menit", "Mulai login lagi"],
    ["Codex: " + C("This address belongs to another sign-in"), "Alamat yang ditempel berasal dari link login yang "
     "lebih lama", "Buka lagi link dari dialog ini dan tempel alamat tujuannya"],
    [C("wake failed ...: model ... not accepted"), "Paket akun itu tidak menyediakan model wake",
     "Pilih model dari daftar di dialog Wake, atau " + C("wake models") + " lalu<br/>" + C("wake model=&lt;id&gt;")
     + " dengan salah satunya, atau " + C("model=default")],
    ["Dialog Wake berisi kolom teks, bukan daftar model", "Daftar model tidak terbaca (tidak ada akun aktif dalam "
     "rotasi, atau provider tidak menjawab); alasannya tertulis di bawah kolom", "Ketik id-nya, atau kosongkan untuk "
     "default; " + C("wake models") + " menampilkan alasan yang sama"],
    [C("wake failed ...: rate-limited"), "Akun sedang kena limit, jadi jendelanya memang sudah berjalan",
     "Tidak perlu diperbaiki; putaran berikutnya melihat jendelanya berjalan"],
    ["<b>Resets</b> menampilkan " + C("not started"), "Tidak ada jendela 5 jam yang berjalan di akun itu",
     "Normal untuk akun yang menganggur. <b>Wake</b> memulainya bila Anda ingin reset lebih cepat"],
    ["Wake otomatis tidak melakukan apa-apa", "Timer mati, atau semua jendela sudah berjalan",
     C("wake status") + "; " + C("doctor")],
    ["Email tampil sebagai " + C("al•••e@e•••.com"), "Sensor email menyala",
     C("hermes account &lt;provider&gt; privacy off") + ", atau tombol mata di halaman"],
], [0.24, 0.34, 0.42])

H1("16. Tanya jawab")
qa = [
    ("Kuota di claude.ai (atau aplikasi pemantau) aman. Kenapa " + C("usage") + " bilang rate-limited?",
     "Itu dua batas yang berbeda. Kuota model adalah yang dipakai bot. Endpoint yang dibaca aplikasi untuk "
     "<i>menampilkan</i> kuota itu punya batas permintaan sendiri. Saat batas itu tercapai, hanya tampilannya yang "
     "terdampak: bot tetap jalan, dan plugin menampilkan nilai terakhir yang diketahui."),
    ("Apakah di Windows harus pakai WSL?", "Tidak. Sejak 3.13.0 plugin jalan di instalasi Windows milik Hermes "
     "sendiri: timer menjadi task Task Scheduler, peringatan menjadi notifikasi Windows, dan semua perintah serta "
     "halaman Accounts sama seperti di Linux. Hermes di dalam WSL juga tetap bisa; itu dihitung sebagai Linux."),
    ("Apakah plugin memakai token AI?", "Hanya untuk " + C("wake") + ", dan hanya bila Anda menjalankannya atau "
     "menyalakan " + C("wake auto-on") + ": satu request dengan jawaban satu kata per wake, yang membuat jendela tetap di "
     "0%. Selebihnya plugin hanya membaca pemakaian dan mengurutkan pool tanpa memanggil model."),
    ("Perlukah wake otomatis dinyalakan?",
     "Berguna untuk pool yang punya jam menganggur: akun yang menunggu pekerjaan sudah punya jendela berjalan, jadi reset "
     "datang lebih cepat begitu pekerjaan tiba. Biayanya paling banyak sekitar 5 request kecil per akun per hari. Pool "
     "yang sibuk sepanjang hari hampir tidak mendapat apa-apa, karena jendelanya sudah berjalan. Wake tidak menambah "
     "kuota."),
    ("Apakah sensor email juga menyembunyikan email di file?",
     "Tidak. Yang disensor adalah yang ditampilkan: output perintah, peringatan, dan halaman. File tetap menyimpan email "
     "asli, supaya target dan " + C("privacy off") + " tetap berfungsi."),
    ("Apakah balance memindahkan sesi yang sedang berjalan ke akun yang lebih longgar?",
     "Tidak. Sesi yang berjalan tetap di akunnya sampai kena limit, karena pindah akun membuang prompt cache. Sesi baru "
     "mengambil akun paling longgar."),
    ("Kenapa akun yang sedang dipakai ada di tengah daftar, dan akun #1 kosong?",
     "Itu tanda balance bekerja. Sesi mulai di akun yang saat itu ada di #1. Pemakaiannya naik, jadi putaran berikutnya "
     "menaruh akun yang lebih longgar di atasnya. #1 adalah tempat sesi baru berikutnya mulai (lihat bagian 5)."),
    ("Apakah ada mode round robin?",
     "Hermes punya (" + C("round_robin") + "), selain " + C("fill_first") + ", " + C("least_used") + ", dan "
     + C("random") + "; plugin tidak punya mode sendiri. Anda bisa menggantinya dengan " + C("strategy") + " atau dari "
     "halaman, tetapi dengan plugin ini tetap pakai " + C("fill_first")
     + ": balance lalu merotasi berdasarkan sisa kuota, bukan giliran. Perbandingan keempatnya ada di bagian 5."),
    ("Apakah plugin mengubah fallback atau model?",
     "Tidak. Fallback, model, dan provider yang dipakai profil tetap di pengaturan Hermes. Satu-satunya pengaturan "
     "terkait model yang ditulis proyek ini adalah " + C("credential_pool_strategies") + ", dan hanya jika Anda minta: "
     + C("setup --strategy") + ", " + C("install.sh --set-strategy") + ", " + C("hermes account &lt;provider&gt; strategy")
     + ", atau dialog rotasi di halaman. " + C("setup") + " juga menulis " + C("plugins.enabled") + " tiap profil dan "
     "menautkan plugin ke sana, untuk halaman dan pelacak sesi."),
    ("Bolehkah akun yang sama dipakai di claude.ai, Claude Code, atau Codex CLI bersamaan?",
     "Boleh, dengan login terpisah di aplikasi itu. Kuotanya berbagi, jadi pemakaian itu ikut terlihat di "
     + C("usage") + ". Jangan menyalin token Hermes ke aplikasi atau perangkat lain."),
    ("Apa yang terjadi jika provider mengubah endpoint pemakaian?",
     C("usage") + ", " + C("report") + ", dan urutan berdasarkan pemakaian berhenti, " + C("doctor")
     + " menandai FAIL, dan pindah akun bawaan Hermes tetap jalan seperti biasa."),
    ("Bisakah bot pekerja menjalankan " + C("hermes account") + "?",
     "Tidak, dan itu disengaja. Perintahnya hanya dipasang di profil default. Di profil bot, plugin hanya mendaftarkan "
     "pelacak sesinya, yang mencatat akun mana yang mereka pakai dan berapa token yang mereka habiskan di akun itu."),
    ("Kenapa token suatu akun banyak tetapi persentasenya rendah, atau sebaliknya?",
     "Persentase berasal dari provider, untuk semua pemakaian akun itu, dengan bobot per jenis token. Sebagian besar "
     "yang dikirim Hermes adalah cache read, yang bobotnya kecil. Pemakaian di Claude Code atau claude.ai menaikkan "
     "persentase tanpa menambah token Hermes."),
    ("Apakah API $ yang saya bayar?",
     "Bukan. Langganan (Claude Pro, Max, Team, ChatGPT Plus, Pro, Team) dibayar tetap berapa pun pemakaiannya. "
     "API $ menghitung token yang sama seolah lewat API provider, jadi Anda bisa melihat nilai langganan itu dan bot "
     "mana yang paling mahal."),
    ("Berapa akun yang dibutuhkan?",
     "Minimal dua. " + C("report") + " memberi tahu jika seluruh pool pernah hampir penuh bersamaan; itu tanda untuk "
     "menambah akun."),
]
for q, a in qa:
    st.append(KeepTogether([Paragraph("<b>" + q + "</b>", s_p), Paragraph(a, s_li)]))

H1("17. Batasan")
LI(["Pemakaian berasal dari <b>endpoint yang tidak didokumentasikan resmi</b>: " + C("api.anthropic.com/api/oauth/usage")
    + " dan " + C("chatgpt.com/backend-api/wham/usage") + " (yang dipakai " + C("/status") + " di Codex CLI). "
    "Endpoint ini bisa berubah atau membatasi permintaan tanpa pemberitahuan. Plugin mengirim header klien yang sama "
    "dengan pembaca pemakaian milik Hermes.",
    "Kuota mingguan Anthropic tidak tersedia untuk akun Team, jadi balance untuk " + C("anthropic") + " memakai jendela 5 jam.",
    C("wake") + " bergantung pada yang ditampilkan endpoint pemakaian saat ini: Anthropic tidak memberi jam reset "
    "selama tidak ada jendela berjalan, Codex menampilkan jendela utuh yang bergeser setiap dibaca. Jika provider "
    "mengubahnya, wake tidak bisa mengenali jendela yang menganggur dan membiarkan akunnya (akun yang disebut namanya "
    "tetap dibangunkan). Wake adalah request yang dibuat dengan akun itu seperti sesi Hermes, jadi tunduk pada "
    "ketentuan paket yang sama.",
    "Sensor email mencakup yang ditampilkan plugin ini. Tempat lain yang menampilkan label akun, seperti "
    + C("hermes auth list") + " atau log Hermes sendiri, tidak disensor.",
    "Codex diuji dengan akun ChatGPT Business asli: login lewat browser, " + C("check") + ", " + C("usage") + ", "
    + C("who") + ", " + C("report") + ", " + C("sessions") + ", " + C("log") + ", " + C("doctor") + ", dan "
    + C("balance --dry-run") + ". Park, unpark, refresh token akun parkir lewat Hermes, balance, dan login dari halaman diuji di "
    "sandbox dengan token palsu (" + C("tests/codex_sandbox.py") + ", " + C("tests/api_sandbox.py") + "); tes login "
    "halaman menjalankan kode " + C("hermes auth add") + " asli dengan panggilan jaringan diganti ("
    + C("tests/hermes_auth_add.py") + "). Perintah "
    "umum untuk provider lain baru dites dengan akun API key.",
    "Hitungan token dimulai saat pelacak sesi pertama kali jalan (di 3.x: " + C("account-pool-tracker") + " 1.1.0) "
    "dan hanya mencakup Hermes di komputer ini. Disimpan 8 hari dalam blok 15 menit, jadi awal periode dibulatkan ke "
    "seperempat jam terdekat. Bot memakai pelacak baru setelah gateway atau sesinya di-restart.",
    "Perkiraan kapan semua akun penuh mengandaikan akun berpaket sama dan beban stabil; ini laju, bukan prediksi "
    "perilaku bot.",
    C("API $") + " memakai harga daftar untuk panjang konteks standar; tarif konteks panjang dan diskon batch tidak "
    "dihitung.",
    C("who") + " mencari sesi lewat stack thread yang sedang berjalan, karena hook " + C("post_api_request")
    + " Hermes tidak menyebut entri pool yang dipakai. Itu butuh " + C("plugins.isolation: in_process") + " (default "
    "Hermes): dengan isolasi " + C("host") + " pelacak tidak mencatat apa pun, jadi " + C("who") + ", token, daftar "
    "sesi, dan peringatan bot kosong, sedangkan usage, balance, park, jadwal, dan perkiraan tetap jalan. Jika suatu "
    "update Hermes mengubah struktur internalnya, " + C("who") + " kosong tetapi bot tidak terganggu (pelacak menelan "
    "semua error). Panggilan tanpa id sesi tidak dihitung, jadi token tidak pernah ditaruh di akun tebakan.",
    "Plugin dibuat untuk " + C("plugins.isolation: in_process") + " (default Hermes). Dengan " + C("host")
    + ", Hermes tidak mendaftarkan perintah CLI plugin, jadi " + C("hermes account") + " (termasuk " + C("balance")
    + " dari timer) tidak ada, pelacak tidak mencatat apa pun, dan backend halaman Accounts berjalan di plugin host, yang belum "
    "diuji.",
    C("add") + " dan " + C("relogin") + " butuh terminal atau halaman Accounts untuk menampilkan link login, menempel "
    "kode, atau mengetik key; tanpa itu mereka langsung berhenti.",
    "Login Codex lewat browser butuh browser di komputer yang menjalankan Hermes (atau halaman Accounts, yang "
    "meneruskan alamat yang ditempel ke Hermes). OpenAI hanya menerima " + C("http://localhost:1455/auth/callback") + " sebagai "
    "alamat kembali untuk client Codex, jadi port-nya tidak bisa diganti.",
    "Halaman Accounts mengikuti SDK desktop plugin Hermes versi Hermes Agent 0.21.6. Perubahan SDK di masa depan bisa "
    "merusak halaman; perintahnya tidak terpengaruh.",
    "Timer butuh systemd (Linux) atau Task Scheduler (Windows 10 dan 11). Di macOS jalankan "
    + C("hermes account all balance") + " tiap beberapa menit dengan launchd atau cron. Di Windows task hanya jalan "
    "selama Anda login.",
    "Dukungan Windows (3.13.0) diuji oleh " + C("tests/windows_sandbox.py") + ", yang menjalankan kode Windows dengan "
    "pengganti Task Scheduler. Bagian Windows-nya (" + C("balance.cmd") + " dan " + C("balance.vbs") + " lewat "
    + C("cmd.exe") + " dan " + C("wscript.exe") + ", junction, file lock) juga dijalankan dengan Python Windows asli "
    "di Wine. Pendaftaran task ke Task Scheduler asli mengikuti cara Hermes mendaftarkan task gateway-nya sendiri "
    "di Windows; workflow " + C("tests") + " (dijalankan manual) mengujinya di runner Windows. Laporkan hasil di "
    "komputer Anda."])

H1("18. Referensi cepat")
table([
    ["Kebutuhan", "Perintah"],
    ["Bantuan", C("hermes account help")],
    ["Cek semua setup", C("hermes account anthropic doctor")],
    ["Kesehatan akun", C("hermes account anthropic check")],
    ["Pemakaian 5 jam", C("hermes account anthropic usage")],
    ["Siapa pakai akun apa", C("hermes account anthropic who")],
    ["Laporan 3 hari", C("hermes account anthropic report --hours 72")],
    ["Sesi termahal, 1 jam", C("hermes account anthropic sessions --hours 1")],
    ["Apa yang berubah hari ini", C("hermes account anthropic log")],
    ["Beban per jam, 7 hari", C("hermes account anthropic report --chart")],
    ["Tambah akun", C("hermes account anthropic add &lt;email&gt;")],
    ["Hapus akun", C("hermes account anthropic remove &lt;email&gt;")],
    ["Parkir sementara", C("hermes account anthropic park &lt;email&gt; --until 17:00")],
    ["Aktifkan lagi", C("hermes account anthropic unpark &lt;email&gt;")],
    ["Parkir tiap minggu", C("hermes account anthropic schedule &lt;email&gt; --every \"mon-fri 09:00-17:00\"")],
    ["Login ulang", C("hermes account anthropic relogin &lt;email&gt;")],
    ["Seimbangkan sekarang", C("hermes account anthropic balance")],
    ["Tes peringatan", C("hermes account anthropic notify test")],
    ["Ringkasan harian jam 08:00", C("hermes account anthropic notify daily=08:00")],
    ["Batas peringatan bot", C("hermes account anthropic notify bots=25")],
    ["Strategi rotasi tiap profil", C("hermes account anthropic strategy")],
    ["Mulai jendela 5 jam yang menganggur", C("hermes account anthropic wake")],
    ["Jaga jendela tetap berjalan", C("hermes account anthropic wake auto-on")],
    ["Sensor email", C("hermes account anthropic privacy on") + " / " + C("off")],
    ["Log timer (Linux)", C("journalctl --user -u hermes-account-balance.service -n 20 -o cat")],
    ["Log timer (Windows)", C("Get-Content $env:LOCALAPPDATA\\hermes\\account-pool-timer\\balance.log -Tail 20")],
    ["Halaman di Desktop", "Sidebar <b>Accounts</b>, atau Ctrl+K " + C("Accounts: open the account pool")],
    ["Setup profil, pelacak sesi, timer", C("hermes account anthropic setup --timer")],
    ["Update plugin", C("hermes plugins update account-pool") + "<br/>(git: " + C("git pull && ./install.sh")
     + ", Windows: " + C("git pull") + " lalu " + C("install.ps1") + ")"],
], [0.30, 0.70])

H1("19. Riwayat versi")
table([
    ["Versi", "Perubahan"],
    ["4.0.1", "Perintah pertama setelah update dari 3.x (misalnya " + C("list") + ") kini memuat pool Hermes "
     "setelah file parkir 3.x dipindahkan, jadi akun yang dipindah tidak lagi tampil sebagai " + C("no longer in the pool")
     + " pada putaran itu."],
    ["4.0.0", "Plugin tidak lagi memegang login sendiri (aturan katalog 11). Akun parkir tetap di pool Hermes, "
     "ditahan di luar rotasi (" + C("mark_exhausted_and_rotate") + ", alasan " + C("parked") + "; unpark = "
     + C("reset_status") + "); daftar parkir " + C("account-pool-parking.json") + " tanpa token; file parkir 3.x "
     "dipindah ke pool sekali secara otomatis; Hermes me-refresh token akun parkir. Login dari halaman menjalankan "
     + C("hermes auth add") + " milik Hermes (" + C("signin.py") + "); kode OAuth milik plugin dihapus. Telegram "
     "lewat home channel bot atau " + C("notify telegram-to=") + ", tanpa membaca " + C(".env") + ". Akun profil "
     "lain dibaca lewat " + C("read_credential_pool") + ". Pelacak sesi digabung ke " + C("account-pool") + " ("
     + C("tracker.py") + "); " + C("setup") + " menautkan plugin ke setiap profil dan menghapus "
     + C("account-pool-tracker") + "; tanpa hitungan ganda selama proses lama masih jalan; panggilan tanpa id sesi "
     "tidak dihitung. Versi " + C("manifest.json") + " diperbaiki. Butuh Hermes 0.21.6."],
    ["3.13.0", "Dukungan Windows tanpa WSL. Timer menjadi task Task Scheduler <b>Hermes Account Balance</b> "
     "(tiap 5 menit selama login, tanpa hak admin, tanpa jendela; " + C("balance.cmd") + ", " + C("balance.vbs")
     + ", " + C("balance.log") + " di " + C("account-pool-timer\\") + "). Notifikasi desktop lewat notifikasi "
     "Windows. Pelacak di profil lain lewat symlink atau directory junction. " + C("install.ps1") + " dan "
     + C("uninstall.ps1") + ". File lock " + C("msvcrt") + ", semua file UTF-8, perintah anak tanpa jendela "
     "konsol. Pelacak 1.5.1. Tes baru " + C("tests/windows_sandbox.py") + " (51 cek) dan " + C("tests/run_all.py")
     + "; bagian Windows juga dijalankan dengan Python Windows asli di Wine; workflow GitHub untuk runner Windows "
     "dan Linux."],
    ["3.12.1", C("setup") + " dan " + C("doctor") + " tidak lagi butuh PyYAML. Hermes 0.21.6 ke atas membaca YAML "
     "dengan modulnya sendiri dan tidak lagi memasang PyYAML, jadi di instalasi baru (misalnya di Windows) "
     + C("setup") + " berhenti dengan " + C("No module named 'yaml'") + ". " + C("config.yaml") + " dibaca "
     "sebagai UTF-8."],
    ["3.12.0", "Dialog Wake: kotak <b>pilih semua</b> di kepala tabel (centang semua akun yang bisa dibangunkan, "
     "atau kosongkan), dan pesan bila semua jendela sedang berjalan. Model wake dipilih dari daftar model akun yang "
     "diambil dari provider (tanpa kuota, disimpan, dibaca ulang paling cepat tiap 6 jam), dengan kolom teks bila "
     "daftar tidak terbaca. <b>Wake N accounts</b> menyimpan model yang dipilih lebih dulu. Perintah baru "
     + C("wake models") + "."],
    ["3.11.1", "Timer juga membaca akun yang diparkir (tanpa kuota) dan me-refresh tokennya, jadi halaman "
     "menampilkan pemakaian, jam reset, dan garis tren akun parkir. Tabel parkir punya kolom <b>Resets</b> ("
     + C("not started") + " bila jendela sudah habis); tooltip garis tren menunjukkan angka tertinggi 24 jam "
     "terakhir. Riwayat menandai bacaan parkir dengan " + C("parked") + ", dan laporan, perkiraan, grafik, serta "
     "ringkasan harian tidak menghitungnya. Tes baru " + C("tests/parked_usage_sandbox.py") + "."],
    ["3.11.0", C("wake") + " memulai jendela 5 jam akun yang menganggur dengan satu request kecil (Anthropic: "
     + C("claude-haiku-4-5") + ", satu token output; Codex: model terkecil akun itu), dengan target, " + C("--dry-run")
     + ", " + C("status") + ", dan " + C("model=") + ". " + C("wake auto-on") + ": timer menjaga jendela tetap "
     "berjalan. " + C("privacy on|off") + " menyensor email di output, peringatan, dan seluruh halaman Accounts. "
     "Halaman: tombol mata, dialog Wake, " + C("not started") + " di kolom Resets. Tes baru "
     + C("tests/wake_privacy_sandbox.py") + "."],
    ["3.10.4", "Unit timer dan perintah yang dijalankan plugin memakai " + C("hermes") + " yang Anda pasang ("
     + C("~/.local/bin/hermes") + "), bukan launcher internal di dalam " + C("~/.hermes") + "."],
    ["3.10.3", "Timer menyeimbangkan semua provider yang punya akun (" + C("hermes account all balance") + "), jadi "
     "akun Codex atau provider lain yang ditambahkan belakangan ikut tanpa " + C("setup") + " kedua. Ringkasan "
     "harian tidak dikirim untuk provider yang diam seharian. " + C("install.sh --help") + " tidak lagi mencetak "
     "satu baris kode."],
    ["3.10.2", "Akun Codex dari workspace ChatGPT Business dan Enterprise bisa ditambahkan: " + C("add")
     + " dan " + C("relogin") + " untuk " + C("openai-codex") + " login lewat browser (kembali ke "
     + C("localhost:1455") + "), " + C("--device") + " untuk kode perangkat. Halaman Accounts menawarkan keduanya, "
     "menerima alamat yang ditempel bila browser di komputer lain, dan kembali ke langkah pertama bila login ditolak. "
     "Login tidak bisa selesai dua kali; " + C("doctor") + " tidak lagi menulis " + C("-0 min ago") + ". Tes baru "
     + C("tests/codex_sandbox.py") + " untuk semua fitur Codex."],
    ["3.10.1", "Dipasang dari repo ini, bukan dari katalog plugin Hermes; perilaku tidak berubah. Plugin tetap "
     "mengurus login sendiri (park, usage live, cek email, login di halaman Accounts), jadi tidak memenuhi aturan "
     "katalog 11. Dokumentasi: alasan tidak masuk katalog, instalasi dengan " + C("install.sh") + " atau "
     + C("hermes plugins install") + " beserta 12 temuan pemindaian Hermes (di terminal dijawab " + C("y") + ")."],
    ["3.10.0", "Siap untuk katalog plugin Hermes. Perintah baru " + C("setup") + " (profil, pelacak, " + C("--timer")
     + ", " + C("--strategy") + ", " + C("--undo") + "); unit systemd ditulis " + C("setup") + ", folder "
     + C("systemd/") + " dihapus, " + C("install.sh") + " memanggil " + C("setup --yes") + ". Tanpa terminal, "
     + C("add") + "/" + C("relogin") + " langsung berhenti dan semua pertanyaan " + C("[y/N]") + " dijawab tidak. "
     "Perbaikan: jadwal parkir lebih dari sehari lagi menulis harinya dua kali. Dokumentasi: screenshot, instalasi "
     "dari katalog, pengungkapan keamanan, README pelacak."],
    ["3.9.1", "Peringatan bot: sekali per bot per 6 jam (sebelumnya bisa berulang saat bot naik-turun di sekitar "
     "batas), dan batas dua kali lipat selama profil belum punya jam biasa. Perkiraan membaca ujung riwayat saja. "
     + C("sessions") + " untuk provider tanpa akun menyebutnya."],
    ["3.9.0", "Peringatan bot yang jauh di atas biasanya (" + C("notify bots=") + "), log aktivitas (" + C("log")
     + " dan tab Activity), perkiraan kapan semua akun ≥ 90% (" + C("usage") + ", " + C("report") + ", ringkasan, "
     "halaman), token per sesi atau tugas Kanban (" + C("sessions") + ", pelacak 1.5.0, tabel di tab Report)."],
    ["3.8.1", "Pelacak 1.4.0 mencatat versi, id proses, dan tugas Kanban. " + C("doctor") + " dan halaman menyebut "
     "proses yang masih memakai pelacak lama (gateway, Hermes Desktop, sesi panjang) beserta perbaikannya. Token tanpa "
     "nama bot berlabel " + C("(older tracker, no name)") + "."],
    ["3.8.0", "Strategi rotasi dari plugin: " + C("strategy") + " (lihat atau ubah per profil, lewat "
     + C("hermes config set") + " milik Hermes) dan dialog rotasi di halaman; tombol <b>Use fill_first</b> di banner. "
     + C("doctor") + ": nilai strategi yang tidak dikenal kini WARN. Kartu token tidak lagi terpotong."],
    ["3.7.0", "Token per bot dan per model (pelacak 1.3.0), harga API di " + C("report") + " dan halaman, "
     "ringkasan harian (" + C("notify daily=HH:MM") + "), grafik beban per jam 7 hari (" + C("report --chart")
     + " dan tab Report), jadwal parkir mingguan (" + C("schedule") + "/" + C("unschedule") + " dan tombol di halaman)."],
    ["3.6.1", "Halaman Accounts: strategi rotasi Hermes di header, banner bila ada profil yang tidak memakai "
     + C("fill_first") + ", penjelasan bahwa sesi berjalan tetap di akunnya, sejak kapan sesi di suatu akun. "
     "Perbaikan: tooltip beberapa baris kini tetap terpisah per baris."],
    ["3.6.0", "Jumlah token per akun: pelacak sesi 1.1.0 menghitung token setiap panggilan API, " + C("report")
     + " dan halaman Accounts menampilkannya. Perbaikan: daftar profil Telegram di tab Alerts kini mengikuti tema."],
    ["3.5.1", "Perbaikan: halaman Accounts gagal (" + C("backend did not answer") + ") saat Desktop memakai profil selain "
     "default. " + C("install.sh") + " kini mencantumkan " + C("account-pool") + " di semua profil (tanpa perintah atau "
     "tool di sana), " + C("doctor") + " memeriksanya."],
    ["3.5.0", "Halaman Accounts di Hermes Desktop: tabel akun, pemakaian, sesi, report, health, alerts, chip status "
     "bar, park/unpark/remove/balance, tambah akun dan login ulang dari halaman. Uji backend dan UI di " + C("tests/") + "."],
    ["3.4.3", "Dokumentasi ditulis ulang (README dan panduan ini). Tanpa perubahan kode."],
    ["3.4.2", "Cadangan \"last known\" mencari di beberapa snapshot terakhir, bertahan 15 menit penuh."],
    ["3.4.1", "Permintaan pemakaian memakai header klien yang sama dengan Hermes; jauh lebih jarang kena 429."],
    ["3.4.0", "Validasi input (" + C("--until") + ", " + C("--threshold") + ", " + C("--hours") + ", " + C("--minutes")
     + ", provider), " + C("add --key")
     + " aman, alasan n/a di " + C("usage") + ", cadangan nilai terakhir, doctor mengecek cakupan timer."],
    ["3.3.x", "Adapter " + C("openai-codex") + "; petunjuk login yang benar; Ctrl+C saat login berhenti dengan bersih."],
    ["3.2.0", C("add") + " dan " + C("remove") + " dengan verifikasi email."],
    ["3.1.0", "Adapter provider; perintah umum untuk semua provider di credential pool."],
    ["3.0.0", "Rilis publik pertama: balance, park/unpark, who, report, relogin, doctor, peringatan, timer."],
], [0.12, 0.88])
P("Daftar lengkap ada di " + C("CHANGELOG.md") + " di repo.")


if __name__ == "__main__":
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    Doc(OUT, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=20 * mm,
        title="Hermes account-pool plugin", author=REPO).multiBuild(st, onFirstPage=footer, onLaterPages=footer)
    print(OUT)
