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
from reportlab.platypus import (CondPageBreak, KeepTogether, PageBreak, Paragraph, Preformatted,
                                SimpleDocTemplate, Spacer, Table, TableStyle)
from reportlab.platypus.tableofcontents import TableOfContents

VERSION = "3.5.0"
REPO = "github.com/roqianjas/hermes-account-pool"
FOOTER = f"Hermes plugin account-pool {VERSION} · {REPO}"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hermes-account-pool.pdf")

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
       [VERSION, REPO, "Hermes Agent ≥ 0.21, Linux + systemd", "MIT"]], [0.12, 0.46, 0.30, 0.12])
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
    ["Tahu bot mana memakai akun apa", "Tidak ada", C("who")],
    ["Tahu ada login mati atau pool penuh", "Tidak dilaporkan", "Peringatan desktop dan Telegram"],
    ["Akun macet setelah refresh token gagal saat jaringan putus", "Menunggu cooldown",
     "Dicoba ulang otomatis tiap 5 menit"],
    ["Melihat semuanya di satu tempat", "Tidak ada", "Halaman Accounts di Hermes Desktop (bagian 8)"],
], [0.28, 0.32, 0.40])
P("Plugin mengubah pool hanya lewat API " + C("CredentialPool") + " milik Hermes sendiri, dan tidak memakai token AI.")
P("Semua perintah memakai pola yang sama, <b>provider dulu, baru aksi</b>:")
code("hermes account <provider> <action> [target] [options]")

H1("2. Mulai cepat")
code("""
git clone https://github.com/roqianjas/hermes-account-pool.git
cd hermes-account-pool
./install.sh --set-strategy                      # plugin, strategi fill_first, timer 5 menit

hermes account anthropic add alice@example.com   # satu login per akun, terverifikasi
hermes account anthropic add bob@example.com
hermes account anthropic doctor                  # semua OK?
hermes account anthropic usage                   # pemakaian live per akun
""")
P("Setelah itu timer menjaga urutan pool secara otomatis. Sehari-hari yang paling sering dipakai: " + C("usage")
  + ", " + C("who") + ", " + C("park") + ", dan " + C("doctor") + ". Di Hermes Desktop, restart aplikasinya sekali "
  "lalu nyalakan halamannya di Capabilities &gt; Plugins untuk mendapat semua itu dalam satu halaman (bagian 8).")

H1("3. Persyaratan")
LI(["Hermes Agent ≥ 0.21 di Linux. Timer butuh systemd user service (" + C("systemctl --user") + ").",
    "Dua akun atau lebih dari provider yang sama. Dukungan pemakaian bawaan: Claude Pro / Max / Team ("
    + C("anthropic") + ") dan ChatGPT Plus / Pro / Team (" + C("openai-codex") + "). Provider lain mendapat "
    "perintah umum (bagian 12).",
    "Opsional: " + C("notify-send") + " (paket " + C("libnotify-bin") + ") untuk notifikasi desktop, dan bot "
    "Telegram yang sudah diatur di Hermes dengan " + C("TELEGRAM_ALLOWED_USERS") + " untuk peringatan Telegram.",
    "Opsional: Hermes Desktop dengan dukungan desktop plugin, untuk halaman Accounts. Diuji dengan Hermes Agent 0.21.5."])

H1("4. Instalasi, update, uninstall")
H2("4.1 Instalasi")
code("""
git clone https://github.com/roqianjas/hermes-account-pool.git
cd hermes-account-pool
./install.sh --set-strategy
""")
P(C("install.sh") + " mengerjakan lima hal:")
OL(["Menyalin " + C("account-pool") + " (beserta halaman Hermes Desktop) dan " + C("account-pool-tracker") + " ke " + C("$HERMES_HOME/plugins/")
    + " (biasanya " + C("~/.hermes/plugins/") + "), lalu mengaktifkan " + C("account-pool") + " <b>hanya di profil default</b>.",
    "Membuat symlink dan mengaktifkan " + C("account-pool-tracker") + " di setiap profil di " + C("$HERMES_HOME/profiles/")
    + ", supaya " + C("who") + " bisa melihat semua bot.",
    "Dengan " + C("--set-strategy") + ": mengatur " + C("credential_pool_strategies.&lt;provider&gt;: fill_first")
    + " di profil default dan semua profil lain. " + C("balance") + " membutuhkannya (bagian 5).",
    "Memasang dan menyalakan " + C("hermes-account-balance.timer") + " (balance tiap 5 menit), lalu menjalankannya sekali.",
    "Menjalankan " + C("hermes account &lt;provider&gt; doctor") + "."])
table([
    ["Opsi", "Fungsi"],
    [C("--provider &lt;nama&gt;"), "Provider yang diseimbangkan timer (default " + C("anthropic") + "). Ulangi untuk "
     "beberapa provider: " + C("--provider anthropic --provider openai-codex") + ". Masing-masing mendapat baris "
     + C("ExecStart") + " sendiri."],
    [C("--set-strategy"), "Atur " + C("fill_first") + " untuk tiap provider di semua profil. Tanpa opsi ini strategi "
     "tidak disentuh, dan " + C("doctor") + " memberi tahu jika salah."],
    [C("--no-tracker"), "Tanpa pelacak sesi. " + C("who") + " akan kosong."],
    [C("--no-timer"), "Tanpa timer. " + C("balance") + " dijalankan sendiri."],
    [C("-h") + ", " + C("--help"), "Tampilkan opsi."],
], [0.26, 0.74])
P(C("HERMES_HOME") + " kustom dihormati dan ditulis ke file service. Sesi yang sedang berjalan baru memuat pelacak "
  "setelah " + C("/reset") + ", atau setelah gateway/desktop di-restart. Halaman Accounts butuh dua langkah lagi di "
  "Hermes Desktop (bagian 8.1). Cek hasilnya:")
code("""
hermes account anthropic doctor
systemctl --user list-timers hermes-account-balance.timer
""")
H2("4.2 Update")
code("""
cd hermes-account-pool
git pull
./install.sh                # pakai opsi --provider yang sama seperti saat instalasi
""")
P("Folder plugin lama dicadangkan ke " + C("$HERMES_HOME/plugin-backups/&lt;nama&gt;.&lt;waktu&gt;") + " (di luar "
  + C("plugins/") + ", jadi tidak pernah dimuat dua kali). Akun, akun parkir, riwayat, dan pengaturan tetap. Tanpa "
  + C("--set-strategy") + ", strategi tidak diubah. Restart Hermes Desktop setelah update supaya halaman dan "
  "backend-nya yang baru ikut dimuat.")
H2("4.3 Uninstall")
code("./uninstall.sh")
P("Timer, kedua plugin (termasuk halaman Accounts), dan symlink pelacak dihapus. Akun di credential pool <b>tidak</b> disentuh. Akun yang "
  "diparkir <b>tidak</b> dikembalikan ke rotasi: skrip memperingatkan dan meminta konfirmasi, jadi " + C("unpark")
  + " dulu jika ingin akun itu kembali. File data dan " + C("credential_pool_strategies") + " tetap; skrip "
  "menampilkan daftar file yang bisa dihapus manual.")

H1("5. Konsep dasar")
H2("Credential pool dan strategi fill_first")
P("Hermes menyimpan akun tiap provider dalam satu daftar di " + C("~/.hermes/auth.json") + ", dipakai bersama "
  "semua profil. Pengecualian: profil yang pernah menjalankan " + C("hermes -p &lt;profil&gt; auth add") + " punya "
  "pool sendiri (" + C("doctor") + " memperingatkannya).")
P("Dengan " + C("fill_first") + ", sesi baru mengambil akun sehat paling atas. Saat kena limit, Hermes memindahkan "
  "sesi ke akun berikutnya. " + C("balance") + " bekerja dengan mengubah urutan daftar ini, jadi butuh "
  + C("fill_first") + ". Dengan " + C("round_robin") + " urutan diacak setiap sesi baru dan balance tidak berpengaruh.")
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
  report   [--hours N]                  riwayat: beban per akun, jam tersibuk (adapter)
  add      <email> [--key] [--yes]      tambah akun: terverifikasi, tanpa duplikat
  remove   <target> [--yes]             hapus login akun (akun parkir juga)
  park     <target> [--until T]         keluarkan akun dari rotasi
  unpark   <target>                     kembalikan akun yang diparkir
  relogin  <target> [--yes]             login ulang, terverifikasi, label dan posisi tetap
  balance  [--dry-run] [--threshold N]  urutkan, istirahatkan >= N% (90), pulihkan, alert
  doctor                                periksa strategi, timer, file, pool, peringatan
  notify   [status|test|...]            saluran peringatan: desktop dan Telegram
  help                                  bantuan
""")
P("<b>Target</b> adalah label akun (email), nomor urut di " + C("list") + ", atau id. " + C("unpark")
  + " menerima label atau id. Contoh output di bawah berdasarkan pool sungguhan, dengan nama akun diganti.")
table([
    ["Aksi", "Mengubah?", "Aksi", "Mengubah?"],
    [C("list") + ", " + C("check") + ", " + C("who") + ", " + C("report") + ", " + C("doctor") + ", " + C("help"),
     "Tidak", C("add") + ", " + C("remove") + ", " + C("park") + ", " + C("unpark") + ", " + C("relogin") + ", "
     + C("balance"), "Ya"],
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
    [C("DEAD: sign in again"), "Provider menolak refresh token", C("relogin &lt;target&gt;") + " (7.8)"],
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
    "parkir karena refresh token hanya bisa dipakai sekali."])
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
[anthropic] usage report: last 24h (45 snapshots, 5.7h covered, from 10-10 12:53)
  'used' adds up 5-hour-window percent: 100 = one full 5-hour window.
  account                              used  share  peak  time >= 90%
  heidi@example.com                      17    28%   17%         0 min
  bob@example.com                        11    18%    9%         0 min
  carol@example.com                      11    18%   11%         0 min
  ...
  total                                  60
  Busiest hours: 18:00-19:00 (25), 13:00-14:00 (18), 17:00-18:00 (14)
  Time with EVERY account >= 90%: 0 min
""")
LI([C("used") + ": total kenaikan pemakaian. 100 berarti setara satu jendela 5 jam penuh. " + C("peak")
    + ": nilai tertinggi. " + C("time >= 90%") + ": berapa lama akun hampir habis.",
    "Dengan data minimal 2 jam dan beban nyata, laporan memberi saran: jika <b>semua akun ≥ 90%</b> pernah terjadi "
    "bersamaan, laporan menyarankan menambah akun; jika satu akun menanggung lebih dari separuh beban, laporan "
    "mengarahkan ke " + C("who") + ".",
    "Default 24 jam (" + C("--hours N") + "). Riwayat mencakup minimal 14 hari terakhir."])
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
    "akun yang mendekati limit mingguan."])
H2("7.7 balance")
code("""
$ hermes account anthropic balance --dry-run       # rencana saja
$ hermes account anthropic balance                 # jalankan (otomatis tiap 5 menit)
2026-10-10 18:39:48 [anthropic] balance (dry run):
  - order: frank(2%) > erin(3%) > dave(3%) > alice(4%) > carol(5%) > bob(7%) > ...
""")
P(C("--threshold N") + " (1 sampai 100, default 90) mengatur ambang istirahat. Baris lain yang bisa muncul: "
  + C("unpark X (park --until ... reached)") + ", " + C("recovered: X (token refresh retried)") + ", "
  + C("bench X (93%) until 17:10") + ", " + C("release X (40%)") + ". Cara kerjanya di bagian 10.")
H2("7.8 relogin")
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
    "Ctrl+C membatalkan dengan bersih."])
H2("7.9 doctor", need=85)
code("""
$ hermes account anthropic doctor
[anthropic] doctor
  OK    strategy fill_first in 6 profiles
  OK    every profile uses the shared account pool
  OK    session tracker active in every profile
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
  "menyertakan perbaikannya. Exit code 1 jika ada FAIL. Untuk provider tanpa akun: "
  + C("not in use, nothing to check") + ".")
H2("7.10 notify")
code("""
hermes account anthropic notify                         # status
hermes account anthropic notify test                    # kirim pesan tes ke semua saluran
hermes account anthropic notify desktop-off             # / desktop-on
hermes account anthropic notify telegram-off            # / telegram-on
hermes account anthropic notify telegram-via=<profil>   # bot profil mana yang mengirim
""")
P("Penjelasan lengkap di bagian 9.")
H2("7.11 help, pesan salah, dan exit code")
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
    [C("hermes account anthropic usage --hours 5"), "--hours only applies to: report"],
    [C("... park X --until 25:99"), "Cannot read --until '25:99'. Use HH:MM (e.g. 17:00), +2h, 90m, or 'YYYY-MM-DD HH:MM'."],
    [C("hermes account anthorpic list"), "Unknown provider 'anthorpic'. Providers in your pool: anthropic. All providers: hermes auth list"],
], [0.40, 0.60])
table([
    ["Exit code", "Arti"],
    ["0", "Selesai"],
    ["1", "Perintah jalan dan menemukan masalah: " + C("check") + "/" + C("doctor") + " gagal, login dibuang atau "
     "gagal, remove ditolak, konfirmasi dijawab tidak (atau Ctrl+D), " + C("notify test") + " tidak sampai ke saluran mana pun"],
    ["2", "Cara pakai salah: aksi, provider, target, atau opsi tidak ada atau tidak dikenal"],
    ["130", "Dibatalkan dengan Ctrl+C"],
], [0.14, 0.86], keep=True)

H1("8. Halaman Accounts di Hermes Desktop")
P("Plugin " + C("account-pool") + " juga membawa halaman <b>Accounts</b> untuk Hermes Desktop: pool, pemakaiannya, "
  "siapa memakai akun apa, dan semua aksi " + C("hermes account") + " dalam bentuk tombol. Perintahnya tetap jalan "
  "seperti biasa; halaman memakai kode yang sama.")
H2("8.1 Menyalakan halaman")
OL(["Jalankan " + C("install.sh") + " (menyalin halaman dan mengaktifkan " + C("account-pool") + " di profil default).",
    "Restart Hermes Desktop sekali. Desktop menjalankan backend halaman bersama plugin lain yang aktif, jadi sebelum "
    "restart ini halaman belum punya data.",
    "Di <b>Capabilities &gt; Plugins</b>, cari <b>account-pool</b> (Agent + Desktop; nama desktop-nya Accounts) dan "
    "nyalakan bagian <b>Desktop</b>. Halaman ini dikirim dalam keadaan mati, jadi belum muncul apa pun sebelum Anda "
    "menyalakannya."])
P("Setelah itu <b>Accounts</b> muncul di sidebar. Command palette (Ctrl+K) punya " + C("Accounts: open the account pool")
  + ", dan chip di status bar juga membuka halaman ini.")
H2("8.2 Isi halaman")
P("Header berisi pilihan provider, tombol <b>Live usage</b>, <b>Balance now</b>, dan <b>Add account</b>. Baris di "
  "bawahnya menunjukkan umur angka pemakaian dan kapan timer jalan berikutnya.")
table([
    ["Tab", "Isi"],
    ["Accounts", "Empat kartu: akun dalam rotasi, akun parkir, akun tempat sesi berikutnya mulai beserta pemakaiannya, "
     "dan jumlah sesi 30 menit terakhir. Lalu tabel rotasi sesuai urutan pool: status, bar pemakaian 5 jam, garis tren "
     "5 jam terakhir, jam reset (atau " + C("back HH:MM") + " saat diistirahatkan), profil yang memakai akun itu "
     "(arahkan kursor untuk melihat sesi, platform, dan model), serta tombol <b>Sign in again</b>, <b>Park</b>, "
     "<b>Remove</b>. Di bawahnya akun parkir: pemakaian terakhir, sejak kapan, kapan kembali, tombol <b>Unpark</b> dan "
     "<b>Remove</b>. Peringatan aktif tampil sebagai banner di atas; akun mati mendapat tombol <b>Sign in again</b>."],
    ["Report", "Angka " + C("report") + " untuk 24 jam, 3 hari, atau 7 hari: beban per akun, porsi, puncak, waktu "
     "≥ 90%, jam tersibuk, dan saran."],
    ["Health", "Status timer, umur riwayat pemakaian, peringatan aktif. <b>Run doctor</b> menjalankan pemeriksaan "
     + C("doctor") + "; <b>Check accounts</b> menjalankan " + C("check") + " dan menampilkan hasilnya."],
    ["Alerts", "Sakelar desktop dan Telegram, profil yang bot-nya mengirim pesan Telegram, <b>Send a test alert</b>, "
     "dan peringatan yang sedang aktif."],
], [0.14, 0.86])
P("<b>Park</b> menanyakan kapan akun kembali: saat di-unpark, 1 jam lagi, 2 jam lagi, atau jam yang Anda ketik ("
  + C("17:00") + ", " + C("+90m") + ", " + C("2026-10-12 08:00") + ", format yang sama dengan " + C("--until")
  + "). <b>Remove</b> dan <b>Balance now</b> minta konfirmasi dulu. Setiap aksi menampilkan pesan yang sama dengan "
  "perintahnya.")
P("<b>Chip status bar</b> " + C("8/8 · 12%") + " artinya 8 dari 8 akun dalam rotasi bisa dipakai, dan akun tempat "
  "sesi berikutnya mulai ada di 12%. Muncul titik kuning saat ada peringatan aktif, merah saat tidak ada akun yang "
  "bisa dipakai. Chip disembunyikan selama provider belum punya akun atau backend belum dimuat.")
H2("8.3 Tambah akun dan login ulang dari halaman")
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
H2("8.4 Permintaan ke provider")
table([
    ["Anda", "Permintaan"],
    ["Membuka halaman, pindah tab, melihat chip", "Tidak ada. Pemakaian dibaca dari riwayat yang ditulis timer tiap "
     "5 menit."],
    ["Live usage", "Satu permintaan pemakaian per akun, termasuk akun parkir. Paling sering sekali per 2 menit per "
     "provider; tombolnya menghitung mundur."],
    ["Balance now", "Sama dengan " + C("balance") + ". Paling sering sekali per menit, bersama Check accounts."],
    ["Check accounts", "Satu permintaan profil per akun."],
    ["Run doctor", "Satu permintaan pemakaian."],
    ["Add account, Sign in again", "Proses login, lalu satu permintaan profil untuk verifikasi email."],
], [0.34, 0.66])
P("Endpoint pemakaian membatasi permintaan per akun (lihat Troubleshooting), jadi halaman tidak pernah memanggilnya "
  "sendiri.")
H2("8.5 Keamanan halaman")
LI(["Halaman adalah " + C("desktop/plugin.js") + ", sebuah desktop plugin Hermes. Ia hanya mengimpor SDK plugin Hermes "
    "dan React, dan hanya bicara dengan backend-nya sendiri.",
    "Backend-nya " + C("dashboard/plugin_api.py") + ", dipasang Hermes di " + C("/api/plugins/account-pool/")
    + " untuk plugin yang ada di " + C("plugins.enabled") + ". Setiap permintaan wajib membawa session token desktop.",
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
], [0.30, 0.44, 0.26])
LI(["Peringatan dikirim oleh " + C("balance") + ", jadi butuh timer.",
    "<b>Desktop</b>: " + C("notify-send") + ", aktif secara default.",
    "<b>Telegram</b>: aktif otomatis jika Hermes punya bot Telegram. Pesan dikirim lewat " + C("hermes send")
    + " ke user pertama di " + C("TELEGRAM_ALLOWED_USERS") + " (chat pribadi Anda), memakai bot profil default. "
    "Jika bot default belum diatur atau tokennya tidak valid, pakai bot profil lain: "
    + C("notify telegram-via=&lt;profil&gt;") + ".",
    "Jalankan " + C("notify test") + " setelah mengatur."])
P("Pengaturan disimpan di " + C("$HERMES_HOME/account-pool.json") + " (dibuat saat perubahan pertama). File ini "
  "juga boleh diedit; ambang peringatan ada di " + C("alert_all_above") + ":")
code("""
{"notify": {"desktop": true, "telegram": "auto", "telegram_via": "default"},
 "alert_all_above": 80}
""")

H1("10. Cara kerja balance")
P("Setiap putaran, untuk satu provider:")
OL(["<b>Park bertanggal</b>: mengaktifkan lagi akun yang waktu " + C("--until") + "-nya sudah lewat.",
    "<b>Pemulihan</b>: mencoba ulang refresh token akun yang COOLING DOWN.",
    "<b>Pemakaian</b> (butuh adapter): membaca pemakaian semua akun, memperbarui access token yang kedaluwarsa dulu.",
    "<b>Istirahat dan lepas</b>: akun ≥ ambang diistirahatkan sampai jendelanya reset (ditandai "
    + C("[account-pool]") + "); akun yang sudah turun dilepas. Limit asli dari provider tidak pernah disentuh.",
    "<b>Urutan</b>: pemakaian terendah dulu, lalu akun yang diistirahatkan, lalu akun yang pemakaiannya tidak "
    "terbaca, lalu akun DEAD.",
    "<b>Riwayat</b>: satu snapshot per putaran untuk " + C("report") + " dan cadangan \"last known\". Nilai yang "
    "berasal dari cadangan itu tidak pernah ditulis ulang.",
    "<b>Peringatan</b> untuk masalah baru."])
note("<b>Pengaman.</b> Jika <b>semua</b> akun ≥ ambang, hanya akun yang 100% yang diistirahatkan, jadi pool tidak "
     "pernah dikosongkan karena \"hampir penuh\". Jika pemakaian tidak terbaca sama sekali, urutan tidak diubah; "
     "pemulihan, unpark terjadwal, dan peringatan tetap jalan. Sesi yang sedang berjalan tidak dipindah, karena "
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
    "<b>Provider tambahan</b>: jalankan ulang " + C("./install.sh --provider anthropic --provider openai-codex")
    + ", atau tambah satu baris " + C("ExecStart=... account &lt;provider&gt; balance") + ". " + C("doctor")
    + " memperingatkan jika timer tidak mencakup provider yang punya akun.",
    "Timer tidak memakai token AI; ia hanya memanggil endpoint pemakaian."])

H1("12. Provider dan Codex")
table([
    ["Fitur", "Provider"],
    [C("list") + ", " + C("check") + ", " + C("add") + "/" + C("remove") + ", " + C("park") + "/" + C("unpark")
     + " (+ " + C("--until") + "), " + C("who") + ", " + C("doctor") + ", peringatan login, pemulihan cooling down",
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
     + C("providers.py") + ". Hanya di profil default."],
    [C("~/.hermes/plugins/account-pool/desktop/"), "Halaman Accounts untuk Hermes Desktop. Desktop menyalinnya ke "
     + C("~/.hermes/desktop-plugins/account-pool/") + "."],
    [C("~/.hermes/plugins/account-pool/dashboard/"), "Backend halaman (" + C("plugin_api.py") + ") dan manifest-nya."],
    [C("~/.hermes/plugins/account-pool-tracker/"), "Pelacak sesi; di-symlink ke " + C("profiles/*/plugins/")
     + ". Tanpa perintah, tanpa tool, tanpa token."],
    [C("~/.hermes/auth.json"), "Credential pool bersama semua profil (milik Hermes)"],
    [C("~/.hermes/account-pool-parked.json"), "Akun yang diparkir. <b>Berisi token OAuth.</b>"],
    [C("~/.hermes/account-pool-sessions.json"), "Sesi dan akunnya, 24 jam terakhir (tanpa token)"],
    [C("~/.hermes/account-pool-history.jsonl"), "Riwayat pemakaian, satu snapshot per putaran timer. Dipangkas ke "
     "14 hari terakhir saat file melewati 3 MB."],
    [C("~/.hermes/account-pool-alerts.json"), "Peringatan yang sudah terkirim (satu pesan per kejadian)"],
    [C("~/.hermes/account-pool.json"), "Pengaturan peringatan"],
    [C("~/.config/systemd/user/") + "<br/>" + C("hermes-account-balance.{service,timer}"), "Timer 5 menit"],
], [0.48, 0.52])
P("Cara token diperlakukan:")
LI(["Semua file data berizin 600. Token tidak pernah dicetak atau dicatat di log; token hanya masuk ke header "
    "permintaan ke endpoint provider itu sendiri.",
    "Plugin hanya menghubungi API provider (pemakaian, profil, refresh token, login) dan, untuk peringatan, Telegram "
    "lewat " + C("hermes send") + " milik Hermes. Tidak ada tujuan lain.",
    "Halaman Accounts tidak menerima token: backend-nya hanya mengirim label, id, status, dan angka.",
    "Refresh token bisa sekali pakai. Setiap refresh langsung ditulis kembali, dengan file lock untuk akun parkir.",
    "API key untuk " + C("add --key") + " dibaca tanpa ditampilkan di dalam plugin, tidak pernah dari command line.",
    "Plugin utama hanya di profil default, jadi profil bot tidak bisa mengubah akun."])

H1("14. Memaksa akun tertentu")
code("""
# Cara 1: parkir akun yang tidak ingin dipakai (bisa sementara)
hermes account anthropic park frank@example.com --until 17:00

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
    [C("who") + " kosong", "Sesi dimulai sebelum pelacak dipasang", C("/reset") + " sesi, atau restart gateway/desktop"],
    ["Tidak ada pesan Telegram", "Token bot profil pengirim tidak valid", C("notify test") + "; ganti " + C("telegram-via")],
    [C("report") + ": not enough history", "Timer mati atau baru dipasang", C("doctor") + ", tunggu beberapa putaran"],
    ["Akun " + C("--until") + " tidak kembali", "Timer mati", C("systemctl --user enable --now") + "<br/>" + C("hermes-account-balance.timer")],
    ["doctor: strategy is not fill_first", "Profil memakai " + C("round_robin") + " atau strategi lain",
     C("hermes -p &lt;profil&gt; config set") + "<br/>" + C("credential_pool_strategies.&lt;provider&gt;") + "<br/>" + C("fill_first")],
    ["doctor: profiles with their OWN pool", "Pernah menjalankan " + C("hermes -p &lt;profil&gt; auth add"),
     "Hapus entri di profil itu, lalu tambah akun dari profil default"],
    ["doctor: last run failed", C("balance") + " terakhir gagal", C("journalctl --user -u") + "<br/>" + C("hermes-account-balance.service -n 20")],
    [C("hermes account") + " tidak dikenal", "Dijalankan dengan -p (plugin hanya di default)", "Jalankan tanpa -p"],
    ["Halaman: " + C("The account-pool backend did not answer"), "Hermes Desktop belum di-restart setelah instalasi, "
     "atau " + C("account-pool") + " belum aktif di profil default", C("hermes plugins enable account-pool") + ", lalu "
     "restart Hermes Desktop"],
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
    ("Apakah plugin mengubah fallback atau model?",
     "Tidak. Fallback, model, dan provider yang dipakai profil tetap di pengaturan Hermes. Satu-satunya pengaturan yang "
     "ditulis proyek ini adalah " + C("credential_pool_strategies") + ", dan hanya jika Anda memakai "
     + C("install.sh --set-strategy") + "."),
    ("Bolehkah akun yang sama dipakai di claude.ai, Claude Code, atau Codex CLI bersamaan?",
     "Boleh, dengan login terpisah di aplikasi itu. Kuotanya berbagi, jadi pemakaian itu ikut terlihat di "
     + C("usage") + ". Jangan menyalin token Hermes ke aplikasi atau perangkat lain."),
    ("Apa yang terjadi jika provider mengubah endpoint pemakaian?",
     C("usage") + ", " + C("report") + ", dan urutan berdasarkan pemakaian berhenti, " + C("doctor")
     + " menandai FAIL, dan pindah akun bawaan Hermes tetap jalan seperti biasa."),
    ("Bisakah bot pekerja menjalankan " + C("hermes account") + "?",
     "Tidak, dan itu disengaja. Perintahnya hanya dipasang di profil default. Bot hanya menjalankan pelacak, yang "
     "mencatat akun mana yang mereka pakai."),
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
    C("who") + " mencari sesi lewat stack thread yang sedang berjalan. Jika suatu update Hermes mengubah struktur "
    "internalnya, " + C("who") + " kosong tetapi bot tidak terganggu (pelacak menelan semua error).",
    C("add") + " dan " + C("relogin") + " dengan OAuth butuh terminal interaktif atau halaman Accounts untuk menempel "
    "kode login. Login Codex dari halaman baru diuji sampai kode perangkat muncul; login Codex penuh belum pernah "
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
    ["Tambah akun", C("hermes account anthropic add &lt;email&gt;")],
    ["Hapus akun", C("hermes account anthropic remove &lt;email&gt;")],
    ["Parkir sementara", C("hermes account anthropic park &lt;email&gt; --until 17:00")],
    ["Aktifkan lagi", C("hermes account anthropic unpark &lt;email&gt;")],
    ["Login ulang", C("hermes account anthropic relogin &lt;email&gt;")],
    ["Seimbangkan sekarang", C("hermes account anthropic balance")],
    ["Tes peringatan", C("hermes account anthropic notify test")],
    ["Log timer", C("journalctl --user -u hermes-account-balance.service -n 20 -o cat")],
    ["Halaman di Desktop", "Sidebar <b>Accounts</b>, atau Ctrl+K " + C("Accounts: open the account pool")],
    ["Update plugin", C("git pull && ./install.sh")],
], [0.30, 0.70])

H1("19. Riwayat versi")
table([
    ["Versi", "Perubahan"],
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
