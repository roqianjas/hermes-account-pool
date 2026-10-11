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

VERSION = "3.10.0"
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
                 "pemakaian, bagi beban sebelum akun habis, parkir akun sementara, lihat bot mana memakai akun apa, "
                 "dan terima peringatan.", s_sub)]
table([["Versi", "Repo", "Butuh", "Lisensi"],
       [VERSION, REPO, "Hermes Agent ≥ 0.21.5, Linux + systemd", "MIT"]], [0.12, 0.46, 0.30, 0.12])
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
    ["Mengeluarkan akun beberapa jam", "Hapus akun, login lagi nanti", C("park --until 17:00") + ", login tetap tersimpan"],
    ["Menyisakan akun di jam yang sama tiap minggu", "Tidak bisa", C("schedule &lt;akun&gt; --every \"mon-fri 09:00-17:00\"")],
    ["Tahu bot mana memakai akun apa", "Tidak ada", C("who")],
    ["Tahu token tiap bot dan nilainya di harga API", "Tidak ada", C("report") + ": token per akun, bot, dan model dengan "
     "harga API, plus beban per jam 7 hari terakhir"],
    ["Tahu ada login mati atau pool penuh", "Tidak dilaporkan", "Peringatan desktop dan Telegram, plus ringkasan harian opsional"],
    ["Akun macet setelah refresh token gagal saat jaringan putus", "Menunggu cooldown",
     "Dicoba ulang otomatis tiap 5 menit"],
    ["Melihat semuanya di satu tempat", "Tidak ada", "Halaman Accounts di Hermes Desktop (bagian 8)"],
], [0.28, 0.32, 0.40])
P("Plugin mengubah pool hanya lewat API " + C("CredentialPool") + " milik Hermes sendiri, dan tidak memakai token AI.")
P("Semua perintah memakai pola yang sama, <b>provider dulu, baru aksi</b>:")
code("hermes account <provider> <action> [target] [options]")

H1("2. Mulai cepat")
code("""
hermes plugins install account-pool --enable           # perintah dan halaman Accounts
hermes plugins install account-pool-tracker --enable   # pelacak sesi
hermes account anthropic setup --timer --strategy      # semua profil, timer, fill_first

hermes account anthropic add alice@example.com   # satu login per akun, terverifikasi
hermes account anthropic add bob@example.com
hermes account anthropic doctor                  # semua OK?
hermes account anthropic usage                   # pemakaian live per akun
""")
P("Tiga baris pertama bisa diganti satu skrip dari git: " + C("./install.sh --set-strategy") + " (bagian 4.2). "
  "Setelah itu timer menjaga urutan pool secara otomatis. Sehari-hari yang paling sering dipakai: " + C("usage")
  + ", " + C("who") + ", " + C("park") + ", dan " + C("doctor") + ". Di Hermes Desktop, restart aplikasinya sekali "
  "lalu nyalakan halamannya di Capabilities &gt; Plugins untuk mendapat semua itu dalam satu halaman (bagian 8).")

H1("3. Persyaratan")
LI(["Hermes Agent ≥ 0.21.5 di Linux. Timer butuh systemd user service (" + C("systemctl --user") + ").",
    "Dua akun atau lebih dari provider yang sama. Dukungan pemakaian bawaan: Claude Pro / Max / Team ("
    + C("anthropic") + ") dan ChatGPT Plus / Pro / Team (" + C("openai-codex") + "). Provider lain mendapat "
    "perintah umum (bagian 12).",
    "Opsional: " + C("notify-send") + " (paket " + C("libnotify-bin") + ") untuk notifikasi desktop, dan bot "
    "Telegram yang sudah diatur di Hermes dengan " + C("TELEGRAM_ALLOWED_USERS") + " untuk peringatan Telegram.",
    "Opsional: Hermes Desktop dengan dukungan desktop plugin, untuk halaman Accounts. Diuji dengan Hermes Agent 0.21.5."])

H1("4. Instalasi, update, uninstall")
P("Instalasi plugin memasang plugin ke satu profil. Proyek ini butuh sedikit lebih: pelacak sesi di setiap profil "
  "(supaya " + C("who") + " melihat semua bot), " + C("account-pool") + " tercantum di setiap profil (supaya Hermes "
  "Desktop bisa menampilkan halamannya profil mana pun yang dijalankan), dan timer jika Anda mau. Bagian itu "
  "dikerjakan " + C("hermes account &lt;provider&gt; setup") + ", setelah cara instalasi mana pun.")
H2("4.1 Instalasi dari katalog plugin Hermes")
code("""
hermes plugins install account-pool --enable
hermes plugins install account-pool-tracker --enable
hermes account anthropic setup --timer --strategy
""")
P("Jalankan di profil default (tanpa " + C("-p") + "): perintahnya ada di sana, dan " + C("setup") + " menautkan "
  "pelacak dari sana ke profil lain. Tanpa katalog, pasang dua folder yang sama langsung dari repo ini (Hermes lalu "
  "memperingatkan bahwa sumbernya belum direview):")
code("""
hermes plugins install roqianjas/hermes-account-pool#plugins/account-pool --enable
hermes plugins install roqianjas/hermes-account-pool#plugins/account-pool-tracker --enable
hermes account anthropic setup --timer --strategy
""")
H2("4.2 Instalasi dari git")
code("""
git clone https://github.com/roqianjas/hermes-account-pool.git
cd hermes-account-pool
./install.sh --set-strategy
""")
P(C("install.sh") + " menyalin " + C("account-pool") + " (beserta halaman Hermes Desktop) dan "
  + C("account-pool-tracker") + " ke " + C("$HERMES_HOME/plugins/") + " (biasanya " + C("~/.hermes/plugins/")
  + "), mengaktifkan " + C("account-pool") + " di profil default, menjalankan "
  + C("hermes account &lt;provider&gt; setup --yes --timer") + " untuk tiap provider (ditambah " + C("--strategy")
  + " jika " + C("--set-strategy") + "), lalu " + C("doctor") + ".")
table([
    ["Opsi", "Fungsi"],
    [C("--provider &lt;nama&gt;"), "Provider yang diseimbangkan timer (default " + C("anthropic") + "). Ulangi untuk "
     "beberapa provider: " + C("--provider anthropic --provider openai-codex") + ". Masing-masing mendapat baris "
     + C("ExecStart") + " sendiri."],
    [C("--set-strategy"), "Atur " + C("fill_first") + " untuk tiap provider di semua profil. Tanpa opsi ini strategi "
     "tidak disentuh, dan " + C("doctor") + " memberi tahu jika salah."],
    [C("--no-tracker"), "Tanpa pelacak sesi. " + C("who") + " akan kosong dan token tidak dihitung."],
    [C("--no-timer"), "Tanpa timer. " + C("balance") + " dijalankan sendiri."],
    [C("-h") + ", " + C("--help"), "Tampilkan opsi."],
], [0.26, 0.74])
H2("4.3 Yang dikerjakan setup", need=70)
code("""
$ hermes account anthropic setup --timer
[anthropic] Setup: the default profile and 2 other profile(s) in /home/you/.hermes
  Accounts page    backend listed in 0 of 2 other profile(s)
  Session tracker  1.5.0, active in 1 of 3 profile(s)
  Balance timer    not installed
  Rotation         fill_first in all 3 profile(s)
Changes:
  - list account-pool in plugins.enabled of worker-1 (Hermes Desktop serves the page's ...)
  - list account-pool in plugins.enabled of worker-2 (...)
  - link the session tracker into worker-1 (.../profiles/worker-1/plugins/account-pool-tracker
    -> /home/you/.hermes/plugins/account-pool-tracker)
  - enable the session tracker in worker-1 (hermes -p worker-1 plugins enable account-pool-...)
  - ... the same for worker-2 ...
  - install the balance timer: systemd user units in /home/you/.config/systemd/user, every
    5 minutes runs: hermes account anthropic balance
Apply these changes? [y/N]
""")
P(C("setup") + " menampilkan keadaan sekarang dan setiap perubahan yang akan dibuat, bertanya sekali, lalu "
  "mengerjakannya satu per satu; setiap perubahan dicatat di log aktivitas (bagian 7.14). Jalankan lagi dan "
  "hasilnya " + C("Nothing to change") + ".")
table([
    ["Bagian", "Yang diubah"],
    ["Halaman Accounts", "Menambahkan " + C("account-pool") + " ke " + C("plugins.enabled") + " setiap profil di "
     + C("$HERMES_HOME/profiles/") + " (alasannya di bagian 8.2). Profil itu tidak mendapat perintah atau tool apa "
     "pun. Profil yang mencantumkan " + C("account-pool") + " di " + C("plugins.disabled") + " dilewati dan disebut."],
    ["Pelacak sesi", "Mengaktifkan " + C("account-pool-tracker") + " di profil default. Di profil lain, membuat "
     "symlink " + C("plugins/account-pool-tracker") + " ke salinan profil default lalu mengaktifkannya dengan "
     + C("hermes -p &lt;profil&gt; plugins enable") + ". Satu salinan berarti satu update untuk semua profil."],
    [C("--timer"), "Menulis " + C("hermes-account-balance.service") + " dan " + C(".timer") + " ke "
     + C("~/.config/systemd/user/") + ", menyalakan timer, dan menjalankan putaran pertama di latar belakang. "
     "Service menjalankan " + C("hermes account &lt;provider&gt; balance") + " tiap 5 menit; " + C("setup --timer")
     + " untuk provider kedua menambah baris sendiri. " + C("HERMES_HOME") + " kustom ditulis ke service. Opsi yang "
     "Anda tambahkan sendiri (" + C("--threshold 85") + ") dan interval yang diubah tetap dipertahankan."],
    [C("--strategy"), "Mengatur " + C("credential_pool_strategies.&lt;provider&gt;: fill_first") + " di profil yang "
     "nilainya lain. " + C("balance") + " membutuhkannya (bagian 5)."],
    [C("--undo"), "Menghapus symlink pelacak dan entri " + C("plugins.enabled") + " di profil lain, serta "
     "mengeluarkan provider itu dari timer (timer hilang jika tidak ada provider tersisa). Kedua plugin di profil "
     "default, akun, akun parkir, pengaturan, file data, dan strategi tetap. Akun parkir yang akan tetap di luar "
     "rotasi disebut namanya."],
    [C("--yes"), "Tanpa pertanyaan. Tanpa terminal (cron, shell milik agent), " + C("setup") + " hanya menampilkan "
     "rencananya dan tidak mengubah apa pun kecuali dengan " + C("--yes") + "."],
], [0.22, 0.78])
P("Semua perubahan config lewat " + C("hermes config set") + " atau " + C("hermes plugins enable") + ", jadi format "
  "dan pengecekan file tetap milik Hermes. Jika pelacak belum terpasang, " + C("setup") + " memberi tahu cara "
  "memasangnya dan melewati bagian itu. Tanpa systemd, " + C("--timer") + " memberi tahu; jalankan " + C("balance")
  + " dengan cara lain (cron).")
P(C("HERMES_HOME") + " kustom dihormati. Sesi yang sedang berjalan baru memuat pelacak setelah " + C("/reset")
  + ", atau setelah gateway/desktop di-restart. Halaman Accounts butuh dua langkah lagi di Hermes Desktop (bagian "
  "8.1). Setelah update, " + C("doctor") + " dan halaman Accounts menyebut proses yang masih memakai pelacak lama. "
  "Profil yang dibuat belakangan perlu " + C("setup") + " lagi supaya halaman tetap jalan saat Desktop memakai "
  "profil itu; " + C("doctor") + " menyebut profil seperti ini. Cek hasilnya:")
code("""
hermes account anthropic doctor
systemctl --user list-timers hermes-account-balance.timer
""")
H2("4.4 Update")
P("Instalasi dari katalog atau repo:")
code("""
hermes plugins update account-pool
hermes plugins update account-pool-tracker
hermes account anthropic setup        # biasanya "Nothing to change"
""")
P("Hermes mengganti folder plugin di profil default. Symlink pelacak di profil lain menunjuk ke folder itu, jadi "
  "semua profil mendapat pelacak baru dengan satu update. Instalasi dari git:")
code("""
cd hermes-account-pool
git pull
./install.sh                # pakai opsi --provider yang sama seperti saat instalasi
""")
P("Folder plugin lama dicadangkan ke " + C("$HERMES_HOME/plugin-backups/&lt;nama&gt;.&lt;waktu&gt;") + " (di luar "
  + C("plugins/") + ", jadi tidak pernah dimuat dua kali). Akun, akun parkir, riwayat, dan pengaturan tetap. Tanpa "
  + C("--set-strategy") + ", strategi tidak diubah. Restart Hermes Desktop setelah update apa pun supaya halaman "
  "dan backend-nya yang baru ikut dimuat.")
H2("4.5 Uninstall")
P("Unpark dulu akun yang diparkir jika ingin akun itu kembali ke rotasi: selama plugin tidak ada, loginnya hanya "
  "tersimpan di " + C("account-pool-parked.json") + ". Instalasi dari katalog atau repo:")
code("""
hermes account anthropic setup --undo     # symlink pelacak, entri halaman, timer
hermes plugins remove account-pool-tracker
hermes plugins remove account-pool
""")
P("Instalasi dari git:")
code("./uninstall.sh")
P("Timer, kedua plugin (termasuk halaman Accounts), symlink pelacak, dan entri " + C("account-pool") + " di "
  + C("plugins.enabled") + " tiap profil dihapus. Akun di credential pool <b>tidak</b> disentuh. Akun yang "
  "diparkir <b>tidak</b> dikembalikan ke rotasi: skrip memperingatkan dan meminta konfirmasi. File data dan "
  + C("credential_pool_strategies") + " tetap; skrip menampilkan daftar file yang bisa dihapus manual.")

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
H2("6.4 Akun Codex (jika nanti dipakai)")
P("Caranya sama: " + C("hermes account openai-codex add &lt;email&gt;") + ", login ChatGPT di browser yang login "
  "sebagai akun itu. Ini hanya menyiapkan akun di pool. Agar profil memakai Codex, atur di pengaturan Hermes (model "
  "atau fallback), bukan lewat plugin.")

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
  remove   <target> [--yes]             hapus login akun (akun parkir juga)
  park     <target> [--until T]         keluarkan akun dari rotasi
  unpark   <target>                     kembalikan akun yang diparkir
  schedule [<target> --every SPEC]      parkir akun tiap minggu; tanpa target: daftar jadwal
  unschedule <target>                   hapus jadwal parkir akun
  relogin  <target> [--yes]             login ulang, terverifikasi, label dan posisi tetap
  balance  [--dry-run] [--threshold N]  urutkan, istirahatkan >= N% (90), pulihkan, alert
  strategy [<nama>] [--only P,...]      strategi rotasi Hermes per profil: lihat atau ubah
  sessions [--hours N]                  sesi (tugas) dengan token terbanyak, beserta harga API
  log      [--hours N]                  apa yang diubah timer, perintah, dan halaman
  doctor                                periksa strategi, timer, file, pool, peringatan
  notify   [status|test|summary|...]    peringatan (desktop, Telegram), ringkasan harian
  help                                  bantuan
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
    [C("usage"), "Tidak*", C("notify"), "Pengaturan"],
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
    "Access token yang kedaluwarsa diperbarui dulu. Untuk akun parkir, pasangan token baru langsung ditulis ke file "
    "parkir karena refresh token hanya bisa dipakai sekali.",
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
    "Data berasal dari plugin pelacak, yang mencatat sesi setelah setiap panggilan API ke model.",
    "Jika sesi pindah akun karena limit, muncul keterangan " + C("(moved from ...)") + ".",
    "Sesi yang sudah berjalan sebelum pelacak dipasang baru muncul setelah " + C("/reset") + ", atau setelah "
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
  "tidak punya harga yang diketahui (model tanpa harga, atau token yang dihitung sebelum pelacak 1.3.0 yang belum "
  "mencatat model); token itu tidak dihitung, bukan ditebak.")
P(C("By profile (bot)") + " dan " + C("By model") + " membagi token yang sama menurut profil Hermes yang "
  "memanggil dan menurut modelnya. Token dari pelacak yang lebih lama dari 1.3.0 tampil sebagai " + C("(older tracker, no name)")
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
LI(["Park memindahkan akun beserta loginnya keluar dari pool ke " + C("account-pool-parked.json")
    + ". Hermes tidak melihatnya, tetapi " + C("usage") + " tetap menampilkan pemakaiannya.",
    "Park bertanggal berakhir pada putaran timer pertama setelah waktunya (paling lambat 5 menit). Akun aktif "
    "terakhir tidak bisa diparkir.",
    "Contoh kegunaan: menyisakan kuota akun tertentu untuk Anda pakai sendiri di claude.ai, atau mengistirahatkan "
    "akun yang mendekati limit mingguan. Untuk jam yang sama setiap minggu, pakai " + C("schedule") + " (7.7)."])
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
P(C("--threshold N") + " (1 sampai 100, default 90) mengatur ambang istirahat. Baris lain yang bisa muncul: "
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
  OK    session tracker active in every profile
  OK    running sessions count with tracker 1.5.0
  OK    Accounts page backend enabled in every profile
  OK    auth.json permissions 600
  OK    account-pool-parked.json permissions 600
  OK    balance timer active, last run 2026-10-10 18:36:09 WIB
  OK    usage history last written 4 min ago
  OK    8 accounts in rotation, 1 parked
  OK    usage endpoint reachable
  OK    alert channels: desktop, telegram via default (delivery is tested with: ...)
  0 failure(s), 0 warning(s).
""")
P("Jalankan setelah instalasi, setelah update Hermes, atau saat bot berperilaku aneh. Setiap baris FAIL atau WARN "
  "menyertakan perbaikannya. Pelacak dimuat saat proses mulai, jadi setelah update gateway, Hermes Desktop, dan sesi "
  "panjang masih memakai pelacak lama; doctor lalu memberi WARN " + C("session tracker 1.5.0 is not loaded yet by: ...")
  + " beserta restart yang dibutuhkan masing-masing. Token tanpa nama bot dalam setengah jam terakhir berarti pelacak "
  "1.2.0 atau lebih lama masih berjalan. Profil dengan strategi lain adalah FAIL (perbaikan: " + C("strategy fill_first")
  + "); nilai yang tidak dikenal Hermes hanya WARN, karena Hermes lalu memakai " + C("fill_first") + "."
  " Exit code 1 jika ada FAIL. Untuk provider tanpa akun: "
  + C("not in use, nothing to check") + ".")
H2("7.12 notify")
code("""
hermes account anthropic notify                         # status
hermes account anthropic notify test                    # kirim pesan tes ke semua saluran
hermes account anthropic notify desktop-off             # / desktop-on
hermes account anthropic notify telegram-off            # / telegram-on
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
    "Token per sesi dihitung pelacak 1.5.0 ke atas, mulai panggilan API pertamanya. Periode yang dimulai lebih awal "
    "menyebut " + C("counted per session since ...") + "; selama bot belum di-restart dengan pelacak baru, sesinya belum "
    "muncul di sini (" + C("doctor") + " menyebut prosesnya).",
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
hermes account anthropic setup                     # profil dan pelacak; rencana, lalu tanya
hermes account anthropic setup --timer --strategy  # plus timer 5 menit dan fill_first
hermes account anthropic setup --undo              # tarik kembali bagian profil dan timer
""")
P("Mengerjakan yang tidak dikerjakan instalasi plugin: backend halaman Accounts dan pelacak sesi di setiap profil, "
  "timer, dan strategi. Penjelasan lengkap di bagian 4.3. Pertanyaan " + C("[y/N]") + " di semua perintah dijawab "
  "<b>tidak</b> jika tidak ada terminal (" + C("no terminal to answer, so no") + ", exit 1); " + C("--yes")
  + " tetap melewatinya.")
H2("7.16 help, pesan salah, dan exit code")
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
     "gagal, remove ditolak, konfirmasi dijawab tidak (atau Ctrl+D, atau tanpa terminal), " + C("add") + "/" + C("relogin") + " tanpa terminal, " + C("notify test") + " atau " + C("notify summary") + " tidak sampai ke saluran mana pun, " + C("unschedule") + " untuk akun tanpa jadwal, " + C("strategy") + " atau langkah " + C("setup") + " yang gagal ditulis"],
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
P("Karena itu " + C("setup") + " (dan " + C("install.sh") + ") menambahkan " + C("account-pool") + " ke " + C("plugins.enabled") + " semua profil. "
  "Selain itu tidak ada yang berubah di profil-profil tersebut:")
LI(["Agent di sebuah profil memuat plugin dari folder " + C("plugins/") + " milik profil itu sendiri, dan "
    + C("account-pool") + " tidak ada di sana (tanpa symlink, berbeda dengan pelacak). Bot tidak mendapat perintah, tool, "
    "atau hook apa pun darinya.",
    "Jika suatu saat sebuah profil memuatnya juga, " + C("register()") + " mengenali profil itu dan tidak mendaftarkan "
    "apa pun. " + C("hermes -p &lt;profil&gt; account ...") + " tetap perintah yang tidak dikenal.",
    "Backend halaman selalu memakai pool bersama di Hermes home default, profil mana pun yang dijalankan Desktop."])
P(C("doctor") + " memeriksa hal ini jika Hermes Desktop punya halamannya: " + C("Accounts page backend enabled in every profile")
  + ", atau peringatan berisi nama profil yang belum mencantumkannya.")
H2("8.3 Isi halaman", need=120)
shot("accounts", "Tab Accounts: delapan akun dalam rotasi beserta pemakaian 5 jam dan bot di tiap akun, satu akun "
     "parkir, dua jadwal parkir, dan perkiraan. Semua akun di gambar adalah data contoh dari tes.")
P("Header berisi pilihan provider, tombol <b>Live usage</b>, <b>Balance now</b>, dan <b>Add account</b>. Baris di "
  "bawahnya menunjukkan umur angka pemakaian dan kapan timer jalan berikutnya.")
table([
    ["Tab", "Isi"],
    ["Accounts", "Baris di bawah header menampilkan strategi rotasi Hermes (arahkan kursor untuk penjelasan tiap "
     "strategi, klik untuk mengubahnya); banner menyebut profil yang tidak memakai " + C("fill_first") + " beserta "
     "tombol <b>Use fill_first</b>. Lima kartu: akun dalam rotasi, akun parkir, akun tempat sesi berikutnya mulai beserta pemakaiannya, "
     "jumlah sesi 30 menit terakhir, dan token 24 jam terakhir beserta harga API-nya. Kartu keenam adalah perkiraan "
     "(bagian 9): kapan semua akun ≥ 90% dengan laju satu jam terakhir. Lalu tabel rotasi sesuai urutan pool: status, bar "
     "pemakaian 5 jam, garis tren 5 jam terakhir, jam reset (atau " + C("back HH:MM") + " saat diistirahatkan), "
     "token 24 jam terakhir (arahkan kursor untuk rincian input, output, cache, jumlah request, harga API, model utama, dan "
     "jendela 5 jam yang sedang berjalan), profil yang memakai akun itu "
     "(arahkan kursor untuk melihat sesi, platform, model, sejak kapan sesi itu di akun ini, dan akun asalnya bila pindah), serta tombol <b>Sign in again</b>, <b>Park</b>, "
     "<b>Park on a schedule</b>, <b>Remove</b>. Ikon kalender di sebelah akun menunjukkan jadwalnya. Di bawahnya akun "
     "parkir: pemakaian terakhir, sejak kapan, kapan kembali (" + C("(schedule)") + " bila diparkir jadwal), tombol "
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
    "tempel di halaman, lalu <b>Finish</b>. <b>Codex</b>: buka halaman yang ditampilkan dan masukkan kodenya; jendela "
    "selesai sendiri setelah Anda konfirmasi.",
    "Hasilnya sama dengan di terminal: " + C("add") + " hanya menyimpan login jika emailnya cocok dan akun belum ada "
    "di pool, lalu langsung balance; " + C("relogin") + " menukar login lama di posisi yang sama hanya jika akunnya "
    "sama."])
note("Tombol <b>Open in default browser</b> juga ada, tetapi browser default sering login sebagai akun lain. Cara aman: "
     "<b>Copy link</b> lalu buka di profil browser yang benar. Login yang tidak selesai dalam 15 menit kedaluwarsa, "
     "<b>Cancel</b> langsung membatalkannya, dan setiap login hanya bisa diselesaikan sekali.")
shot("add-account", "Add account untuk Anthropic: salin link, buka di browser yang login sebagai akun itu, tempel "
     "kodenya, Finish.", width=0.85)
H2("8.5 Permintaan ke provider")
table([
    ["Anda", "Permintaan"],
    ["Membuka halaman, pindah tab, melihat chip", "Tidak ada. Pemakaian dibaca dari riwayat yang ditulis timer tiap "
     "5 menit, token dari pelacak, harga API dari daftar harga Hermes."],
    ["Live usage", "Satu permintaan pemakaian per akun, termasuk akun parkir. Paling sering sekali per 2 menit per "
     "provider; tombolnya menghitung mundur."],
    ["Balance now", "Sama dengan " + C("balance") + ". Paling sering sekali per menit, bersama Check accounts."],
    ["Check accounts", "Satu permintaan profil per akun."],
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
    "Jawaban backend hanya berisi label, id, status, persen, dan waktu. Token tidak pernah keluar dari backend. Data "
    "rahasia login yang sedang berjalan (PKCE verifier Anthropic, device id Codex) tetap di memori backend.",
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
    "<b>Desktop</b>: " + C("notify-send") + ", aktif secara default.",
    "<b>Telegram</b>: aktif otomatis jika Hermes punya bot Telegram. Pesan dikirim lewat " + C("hermes send")
    + " ke user pertama di " + C("TELEGRAM_ALLOWED_USERS") + " (chat pribadi Anda), memakai bot profil default. "
    "Jika bot default belum diatur atau tokennya tidak valid, pakai bot profil lain: "
    + C("notify telegram-via=&lt;profil&gt;") + ".",
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
    "Dihitung dari file pelacak, tanpa permintaan ke provider. Token tanpa nama bot tidak ikut. Sesi tersibuk butuh "
    "pelacak 1.5.0.",
    C("notify bots=25") + " mengubah batas dolar (sekaligus menyalakan), " + C("notify bots-off") + " mematikan. Batas "
    "request, faktor, dan jedanya ada di " + C("alert_bot.requests") + ", " + C("alert_bot.factor") + ", dan "
    + C("alert_bot.cooldown_h") + " di file pengaturan."])
H2("Ringkasan harian", need=70)
P(C("notify daily=08:00") + " mengirim ringkasan 24 jam terakhir sekali sehari, pada putaran timer pertama setelah "
  "jam 08:00, ke saluran yang sama dengan peringatan. Jika dinyalakan setelah jam itu, ringkasan pertama datang "
  "besoknya. " + C("notify summary") + " langsung mengirim satu, sekaligus sebagai pratinjau.")
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
  "dan jadwal parkir di " + C("schedules") + ":")
code("""
{"notify": {"desktop": true, "telegram": "auto", "telegram_via": "default", "daily": "08:00"},
 "alert_all_above": 80,
 "alert_bot": {"on": true, "usd": 15, "requests": 300, "factor": 3, "cooldown_h": 6},
 "schedules": {"anthropic": [{"label": "dave@example.com", "id": "a3b2c3",
                              "days": [0, 1, 2, 3, 4], "from": "09:00", "to": "17:00"}]}}
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
    "<b>Pemulihan</b>: mencoba ulang refresh token akun yang COOLING DOWN.",
    "<b>Pemakaian</b> (butuh adapter): membaca pemakaian semua akun, memperbarui access token yang kedaluwarsa dulu.",
    "<b>Istirahat dan lepas</b>: akun ≥ ambang diistirahatkan sampai jendelanya reset (ditandai "
    + C("[account-pool]") + "); akun yang sudah turun dilepas. Limit asli dari provider tidak pernah disentuh.",
    "<b>Urutan</b>: pemakaian terendah dulu, lalu akun yang diistirahatkan, lalu akun yang pemakaiannya tidak "
    "terbaca, lalu akun DEAD.",
    "<b>Riwayat</b>: satu snapshot per putaran untuk " + C("report") + " dan cadangan \"last known\". Nilai yang "
    "berasal dari cadangan itu tidak pernah ditulis ulang.",
    "<b>Peringatan</b> untuk masalah baru (akun perlu login ulang, semua akun tinggi, bot jauh di atas biasanya), "
    "dan ringkasan harian bila sudah waktunya.",
    "<b>Log aktivitas</b>: setiap perubahan dari langkah 1 sampai 8 dicatat di " + C("account-pool-activity.jsonl")
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
code("""
hermes account anthropic setup --timer                             # pasang / tambah provider
hermes account anthropic setup --undo                              # keluarkan provider
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
    "<b>Provider tambahan</b>: " + C("hermes account openai-codex setup --timer") + " menambah baris "
    + C("ExecStart") + " kedua dan mempertahankan yang pertama. " + C("doctor")
    + " memperingatkan jika timer tidak mencakup provider yang punya akun.",
    "Timer hanya dipasang jika Anda minta (" + C("setup --timer") + ", atau " + C("install.sh") + " tanpa "
    + C("--no-timer") + "). File unit ditulis oleh " + C("setup") + ", bukan diambil dari template.",
    "Timer tidak memakai token AI; ia hanya memanggil endpoint pemakaian (dan saluran notifikasi Anda untuk "
    "peringatan dan ringkasan harian)."])

H1("12. Provider dan Codex")
table([
    ["Fitur", "Provider"],
    [C("list") + ", " + C("check") + ", " + C("add") + "/" + C("remove") + ", " + C("park") + "/" + C("unpark")
     + " (+ " + C("--until") + "), " + C("schedule") + ", " + C("who") + ", token dan harga API, " + C("doctor")
     + ", peringatan login, ringkasan harian, pemulihan cooling down",
     "<b>Semua provider</b> di credential pool (OAuth dan API key)"],
    [C("relogin"), "Provider dengan login OAuth. Verifikasi email butuh adapter identity."],
    [C("usage") + ", " + C("report") + ", urutan " + C("balance") + ", peringatan \"semua akun tinggi\", email asli",
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
    [C("~/.hermes/plugins/account-pool/"), "Plugin utama (perintah " + C("hermes account") + "), adapter di "
     + C("providers.py") + ". Perintahnya hanya terdaftar di profil default."],
    [C("~/.hermes/plugins/account-pool/desktop/"), "Halaman Accounts untuk Hermes Desktop. Desktop menyalinnya ke "
     + C("~/.hermes/desktop-plugins/account-pool/") + "."],
    [C("~/.hermes/plugins/account-pool/dashboard/"), "Backend halaman (" + C("plugin_api.py") + ") dan manifest-nya."],
    [C("~/.hermes/plugins/account-pool-tracker/"), "Pelacak sesi dan penghitung token (mencatat juga versinya, id proses, dan tugas Kanban); di-symlink ke "
     + C("profiles/*/plugins/") + ". Tanpa perintah, tanpa tool, tanpa kredensial."],
    [C("~/.hermes/auth.json"), "Credential pool bersama semua profil (milik Hermes)"],
    [C("~/.hermes/account-pool-parked.json"), "Akun yang diparkir. <b>Berisi token OAuth.</b>"],
    [C("~/.hermes/account-pool-sessions.json"), "Sesi dan akunnya, 24 jam terakhir (tanpa token)"],
    [C("~/.hermes/account-pool-tokens.json"), "Jumlah token per akun, profil, dan model, serta per profil, sesi, dan "
     "model, dalam blok 15 menit, 8 hari terakhir. Hanya angka dan id sesi."],
    [C("~/.hermes/account-pool-activity.jsonl"), "Log aktivitas: apa yang diubah timer, perintah, dan halaman. 30 hari "
     "terakhir, izin 600."],
    [C("~/.hermes/account-pool-history.jsonl"), "Riwayat pemakaian, satu snapshot per putaran timer. Dipangkas ke "
     "14 hari terakhir saat file melewati 3 MB."],
    [C("~/.hermes/account-pool-alerts.json"), "Peringatan yang sudah terkirim (satu pesan per kejadian)"],
    [C("~/.hermes/account-pool-state.json"), "Kapan ringkasan harian terakhir dikirim, dan jendela jadwal yang sudah dijalankan"],
    [C("~/.hermes/account-pool.json"), "Pengaturan: saluran peringatan, ringkasan harian, peringatan bot, jadwal parkir"],
    [C("~/.config/systemd/user/") + "<br/>" + C("hermes-account-balance.{service,timer}"), "Timer 5 menit, ditulis "
     + C("setup --timer")],
], [0.48, 0.52])
P("Cara token diperlakukan:")
LI(["Semua file data berizin 600. Token tidak pernah dicetak atau dicatat di log; token hanya masuk ke header "
    "permintaan ke endpoint provider itu sendiri.",
    "Plugin hanya menghubungi API provider (pemakaian, profil, refresh token, login) dan, untuk peringatan dan "
    "ringkasan harian, Telegram lewat " + C("hermes send") + " milik Hermes. Tidak ada tujuan lain. Harga API "
    "diambil dari file yang sudah dimiliki Hermes.",
    "Halaman Accounts tidak menerima token: backend-nya hanya mengirim label, id, status, dan angka.",
    "Refresh token bisa sekali pakai. Setiap refresh langsung ditulis kembali, dengan file lock untuk akun parkir.",
    "API key untuk " + C("add --key") + " dibaca tanpa ditampilkan di dalam plugin, tidak pernah dari command line.",
    "Plugin utama hanya di profil default, jadi profil bot tidak bisa mengubah akun."])
H2("Pengungkapan keamanan dan privasi", need=60)
P("Ringkasan semua yang dilakukan plugin di luar file miliknya sendiri. Aturan katalog plugin Hermes memintanya "
  "(aturan 11 dan 13), dan ini yang perlu Anda ketahui sebelum menjalankannya. Versi lengkapnya, termasuk daftar "
  "fungsi internal Hermes yang dipakai, ada di README bagian <i>Security and privacy disclosure</i>.")
table([
    ["Hal", "Rincian"],
    ["Menulis kredensial", C("add") + ", " + C("relogin") + ", " + C("remove") + ", " + C("park") + ", " + C("unpark")
     + ", " + C("schedule") + ", dan " + C("balance") + " mengubah pool lewat API " + C("CredentialPool") + " milik "
     "Hermes atau " + C("hermes auth add/remove") + ". " + C("park") + " memindahkan entri beserta token OAuth-nya ke "
     + C("account-pool-parked.json") + " (600, file lock); " + C("balance") + " me-refresh token akun parkir dengan "
     "fungsi refresh Hermes sendiri. Login dari halaman memakai client id dan fungsi token Hermes."],
    ["Jaringan", C("api.anthropic.com") + " (usage, profile), endpoint token OAuth Anthropic lewat Hermes, "
     + C("claude.ai/oauth/authorize") + " (link yang Anda buka sendiri), " + C("chatgpt.com/backend-api/wham/usage")
     + ", " + C("auth.openai.com") + ", dan Telegram lewat " + C("hermes send") + ". Header klien sama dengan "
     "pembaca pemakaian Hermes (" + C("claude-code/2.1.0") + ", " + C("codex_cli_rs") + "). Tanpa telemetri, tanpa "
     "cek update."],
    ["Kerja di latar belakang", "Hanya timer, jika dipasang: " + C("balance") + " tiap 5 menit. Pelacak berjalan "
     "di dalam setiap proses Hermes sebagai hook " + C("post_api_request") + "."],
    ["Perintah yang dijalankan", C("systemctl --user") + ", " + C("notify-send") + ", " + C("hermes config set")
     + ", " + C("hermes plugins enable account-pool-tracker") + ", " + C("hermes auth add/remove") + ", "
     + C("hermes send") + "."],
    ["Dibaca di luar file sendiri", C("config.yaml") + " dan " + C("state.db") + " (read-only) setiap profil, "
     + C("/proc/self/cgroup") + " (apakah proses ini service timer), " + C("/proc/&lt;pid&gt;/cmdline")
     + " proses Hermes (" + C("doctor") + "), file harga Hermes, status unit systemd."],
    ["Ditulis di luar file sendiri", C("auth.json") + "; " + C("config.yaml") + " profil hanya lewat "
     + C("hermes config set") + "/" + C("plugins enable") + " dari " + C("setup") + ", " + C("strategy") + ", "
     "dan dialog rotasi; symlink pelacak di " + C("profiles/*/plugins/") + "; unit systemd."],
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

H1("15. Troubleshooting")
table([
    ["Gejala", "Penyebab umum", "Solusi"],
    [C("usage") + ": n/a (rate-limited) atau \"last known\"", "Endpoint pengukur pemakaian dipanggil sangat sering "
     "(oleh plugin, aplikasi pemantau lain, atau model picker Hermes Desktop). Ini bukan kuota model Anda.",
     "Tunggu beberapa menit. Bot tidak terpengaruh; balance menaruh akun tanpa data di belakang"],
    ["Login: \"Sign in again to continue\"", "Login di browser sudah lama (kebijakan Anthropic)", "Klik, login ulang sebagai akun yang sama"],
    [C("add") + ": discarded", "Browser login sebagai akun lain, atau akun yang sudah ada di pool",
     "Pakai profil Chrome akun itu atau jendela private baru, lalu " + C("add") + " lagi"],
    [C("Cancelled (Ctrl+C). Nothing was added."), "Ctrl+C saat login", "Memang begitu. Jalankan " + C("add") + " lagi saat siap"],
    ["Bot \"retrying in 600s\"", "Akun kena 429 sebelum balance mengistirahatkannya",
     C("hermes account anthropic balance") + ", lalu stop dan kirim ulang pesan"],
    ["check: DEAD", "Login dicabut atau token dipakai aplikasi/perangkat lain", C("hermes account anthropic relogin &lt;email&gt;")],
    ["check: WRONG LABEL / DUPLICATE", "Ditambah lewat " + C("hermes auth add") + " saat browser login akun lain",
     C("relogin") + " akun yang benar, atau " + C("remove &lt;id&gt;") + " entri lebihnya"],
    [C("who") + " kosong", "Sesi dimulai sebelum pelacak dipasang, atau Hermes memakai " + C("plugins.isolation: host"),
     C("/reset") + " sesi, atau restart gateway/desktop. Dengan isolasi " + C("host") + " pelacak tidak bisa melihat "
     "akunnya (bagian 17)"],
    [C("sessions") + " kosong", "Bot masih memakai pelacak lebih lama dari 1.5.0", C("hermes gateway restart") + ", restart "
     "Hermes Desktop; " + C("doctor") + " menyebut prosesnya"],
    [C("doctor") + ": session tracker ... is not loaded yet", "Gateway, Hermes Desktop, atau sesi panjang dimulai sebelum "
     "pelacak di-update", C("hermes gateway restart") + "; restart Hermes Desktop; sesi berganti saat selesai"],
    ["Tidak ada pesan Telegram", "Token bot profil pengirim tidak valid", C("notify test") + "; ganti " + C("telegram-via")],
    [C("report") + ": not enough history", "Timer mati atau baru dipasang", C("doctor") + ", tunggu beberapa putaran"],
    ["Peringatan bot terlalu sering", "Batas bawah terlalu rendah untuk beban Anda", C("notify bots=30") + " (atau "
     + C("bots-off") + "); lihat " + C("sessions --hours 1") + " dulu"],
    ["Akun " + C("--until") + " tidak kembali", "Timer mati", C("hermes account &lt;provider&gt;") + "<br/>" + C("setup --timer")],
    ["Jadwal tidak memarkir akunnya", "Timer mati, akun itu akun aktif terakhir, atau Anda meng-unpark di tengah jendela",
     C("hermes account anthropic schedule") + " menampilkan keadaan tiap jadwal"],
    ["Ringkasan harian tidak datang", "Timer mati, tidak ada saluran aktif, atau dinyalakan setelah jamnya hari ini",
     C("notify") + " menampilkan jam dan hari terakhir terkirim; " + C("notify summary") + " menguji pengiriman"],
    [C("report") + ": API $ " + C("-") + " atau berakhiran " + C("+"), "Model tanpa harga di daftar Hermes, atau token "
     "dari sebelum pelacak 1.3.0", "Tidak perlu diperbaiki; token itu tidak dihargai"],
    ["doctor: strategy is not fill_first", "Profil memakai " + C("round_robin") + " atau strategi lain",
     C("hermes account &lt;provider&gt;") + "<br/>" + C("strategy fill_first") + ", atau <b>Use fill_first</b> di halaman"],
    ["doctor: profiles with their OWN pool", "Pernah menjalankan " + C("hermes -p &lt;profil&gt; auth add"),
     "Hapus entri di profil itu, lalu tambah akun dari profil default"],
    ["doctor: last run failed", C("balance") + " terakhir gagal", C("journalctl --user -u") + "<br/>" + C("hermes-account-balance.service -n 20")],
    [C("hermes account") + " tidak dikenal", "Dijalankan dengan -p (plugin hanya di default)", "Jalankan tanpa -p"],
    ["Halaman: " + C("The account-pool backend did not answer"), "Desktop memakai profil yang belum mencantumkan "
     + C("account-pool") + " (profil baru, atau instalasi sebelum 3.5.1), atau belum di-restart setelah instalasi",
     C("hermes account &lt;provider&gt; setup") + ", lalu restart Hermes Desktop. " + C("doctor") + " menyebut profil yang belum"],
    [C("add needs a terminal") + " / " + C("relogin needs a terminal"), "Dijalankan dari cron, shell agent, atau tempat "
     "lain tanpa terminal, jadi tidak ada yang bisa menempel kode login", "Jalankan di terminal, atau pakai <b>Add "
     "account</b> / <b>Sign in again</b> di halaman"],
    [C("no terminal to answer, so no"), "Perintah yang bertanya dijalankan tanpa terminal", "Jalankan di terminal, "
     "atau tambah " + C("--yes")],
    [C("setup") + ": session tracker not installed", "Hanya " + C("account-pool") + " yang dipasang",
     C("hermes plugins install account-pool-tracker --enable") + ", lalu " + C("setup") + " lagi"],
    ["Tidak ada Accounts di sidebar", "Bagian Desktop plugin masih mati", "Capabilities &gt; Plugins, account-pool, "
     "nyalakan Desktop. Setelah update: Ctrl+K, " + C("Reload desktop plugins")],
    ["Tombol Live usage abu-abu", "Live usage baru jalan kurang dari 2 menit lalu", "Tunggu hitungan mundurnya"],
    ["Login di halaman: " + C("This code belongs to another sign-in"), "Kode berasal dari link login lain, atau "
     "disalin tanpa bagian setelah " + C("#"), "Buka lagi link dari jendela ini dan salin kode lengkapnya"],
], [0.24, 0.34, 0.42])

H1("16. Tanya jawab")
qa = [
    ("Kuota di claude.ai (atau aplikasi pemantau) aman. Kenapa " + C("usage") + " bilang rate-limited?",
     "Itu dua batas yang berbeda. Kuota model adalah yang dipakai bot. Endpoint yang dibaca aplikasi untuk "
     "<i>menampilkan</i> kuota itu punya batas permintaan sendiri. Saat batas itu tercapai, hanya tampilannya yang "
     "terdampak: bot tetap jalan, dan plugin menampilkan nilai terakhir yang diketahui."),
    ("Apakah plugin memakai token AI?", "Tidak. Plugin hanya membaca pemakaian dan mengurutkan pool. Tidak ada model yang dipanggil."),
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
     + ", atau dialog rotasi di halaman. " + C("setup") + " juga menulis " + C("plugins.enabled") + " tiap profil, "
     "untuk halaman dan pelacak."),
    ("Bolehkah akun yang sama dipakai di claude.ai, Claude Code, atau Codex CLI bersamaan?",
     "Boleh, dengan login terpisah di aplikasi itu. Kuotanya berbagi, jadi pemakaian itu ikut terlihat di "
     + C("usage") + ". Jangan menyalin token Hermes ke aplikasi atau perangkat lain."),
    ("Apa yang terjadi jika provider mengubah endpoint pemakaian?",
     C("usage") + ", " + C("report") + ", dan urutan berdasarkan pemakaian berhenti, " + C("doctor")
     + " menandai FAIL, dan pindah akun bawaan Hermes tetap jalan seperti biasa."),
    ("Bisakah bot pekerja menjalankan " + C("hermes account") + "?",
     "Tidak, dan itu disengaja. Perintahnya hanya dipasang di profil default. Bot hanya menjalankan pelacak, yang "
     "mencatat akun mana yang mereka pakai dan berapa token yang mereka habiskan di akun itu."),
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
    "Adapter Codex baru diuji read-only pada akun ChatGPT Team asli; " + C("add") + " dengan login Codex sungguhan "
    "belum pernah dijalankan. Perintah umum untuk provider lain baru dites dengan akun API key.",
    "Hitungan token dimulai saat pelacak 1.1.0 pertama kali jalan dan hanya mencakup Hermes di komputer ini. "
    "Disimpan 8 hari dalam blok 15 menit, jadi awal periode dibulatkan ke seperempat jam terdekat. Pembagian per "
    "profil dan model dimulai dengan pelacak 1.3.0; bot memakai pelacak baru setelah gateway atau sesinya di-restart.",
    "Perkiraan kapan semua akun penuh mengandaikan akun berpaket sama dan beban stabil; ini laju, bukan prediksi "
    "perilaku bot.",
    C("API $") + " memakai harga daftar untuk panjang konteks standar; tarif konteks panjang dan diskon batch tidak "
    "dihitung.",
    C("who") + " mencari sesi lewat stack thread yang sedang berjalan, karena hook " + C("post_api_request")
    + " Hermes tidak menyebut entri pool yang dipakai. Itu butuh " + C("plugins.isolation: in_process") + " (default "
    "Hermes): dengan isolasi " + C("host") + " pelacak tidak mencatat apa pun, jadi " + C("who") + ", token, daftar "
    "sesi, dan peringatan bot kosong, sedangkan usage, balance, park, jadwal, dan perkiraan tetap jalan. Jika suatu "
    "update Hermes mengubah struktur internalnya, " + C("who") + " kosong tetapi bot tidak terganggu (pelacak menelan "
    "semua error).",
    C("add") + " dan " + C("relogin") + " butuh terminal atau halaman Accounts untuk menempel kode login atau "
    "mengetik key; tanpa itu mereka langsung berhenti. Login Codex dari halaman baru diuji sampai kode perangkat muncul; login Codex penuh belum pernah "
    "dijalankan.",
    "Halaman Accounts mengikuti SDK desktop plugin Hermes versi Hermes Agent 0.21.5. Perubahan SDK di masa depan bisa "
    "merusak halaman; perintahnya tidak terpengaruh.",
    "Timer hanya untuk Linux dengan systemd. Perintahnya sendiri jalan di mana pun Hermes jalan."])

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
    ["Log timer", C("journalctl --user -u hermes-account-balance.service -n 20 -o cat")],
    ["Halaman di Desktop", "Sidebar <b>Accounts</b>, atau Ctrl+K " + C("Accounts: open the account pool")],
    ["Setup profil, pelacak, timer", C("hermes account anthropic setup --timer")],
    ["Update plugin", C("hermes plugins update account-pool") + "<br/>(git: " + C("git pull && ./install.sh") + ")"],
], [0.30, 0.70])

H1("19. Riwayat versi")
table([
    ["Versi", "Perubahan"],
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
