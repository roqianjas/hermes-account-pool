import os
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (CondPageBreak, KeepTogether, PageBreak, Paragraph, Preformatted,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

D = "/usr/share/fonts/truetype/dejavu/"
pdfmetrics.registerFont(TTFont("Sans", D + "DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("Sans-Bold", D + "DejaVuSans-Bold.ttf"))
pdfmetrics.registerFont(TTFont("Mono", D + "DejaVuSansMono.ttf"))
pdfmetrics.registerFontFamily("Sans", normal="Sans", bold="Sans-Bold")

INK, MUTED, ACCENT = colors.HexColor("#1f2328"), colors.HexColor("#59636e"), colors.HexColor("#8a5a12")
LINE, CODEBG, HEADBG, NOTEBG = (colors.HexColor(c) for c in ("#d8dee4", "#f4f1ea", "#efe7d6", "#fbf6ea"))

s_title = ParagraphStyle("t", fontName="Sans-Bold", fontSize=20, leading=25, textColor=INK, spaceAfter=4)
s_sub = ParagraphStyle("s", fontName="Sans", fontSize=10, leading=14, textColor=MUTED, spaceAfter=12)
s_h1 = ParagraphStyle("h1", fontName="Sans-Bold", fontSize=13.5, leading=18, textColor=ACCENT, spaceBefore=12,
                      spaceAfter=6, keepWithNext=1)
s_h2 = ParagraphStyle("h2", fontName="Sans-Bold", fontSize=10.5, leading=14, textColor=INK, spaceBefore=8,
                      spaceAfter=4, keepWithNext=1)
s_p = ParagraphStyle("p", fontName="Sans", fontSize=9.5, leading=14, textColor=INK, spaceAfter=5)
s_li = ParagraphStyle("li", parent=s_p, leftIndent=12, bulletIndent=2, spaceAfter=3)
s_cell = ParagraphStyle("c", fontName="Sans", fontSize=8.6, leading=11.5, textColor=INK)
s_cellb = ParagraphStyle("cb", parent=s_cell, fontName="Sans-Bold")
s_code = ParagraphStyle("code", fontName="Mono", fontSize=8.1, leading=11.2, textColor=INK)
W = A4[0] - 36 * mm
st = []


def C(t): return f"<font name='Mono'>{t}</font>"
def P(t): st.append(Paragraph(t, s_p))
def H1(t): st.extend([CondPageBreak(45 * mm), Paragraph(t, s_h1)])
def H2(t): st.extend([CondPageBreak(38 * mm), Paragraph(t, s_h2)])
def LI(items): st.extend(Paragraph(i, s_li, bulletText="•") for i in items)


def code(text):
    t = Table([[Preformatted(text.strip("\n"), s_code)]], colWidths=[W])
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


def table(rows, widths):
    data = [[Paragraph(c, s_cellb if r == 0 else s_cell) for c in row] for r, row in enumerate(rows)]
    t = Table(data, colWidths=[W * w for w in widths], repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), HEADBG), ("GRID", (0, 0), (-1, -1), 0.4, LINE),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                           ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    st.extend([t, Spacer(1, 8)])


def footer(c, doc):
    c.saveState()
    c.setFont("Sans", 7.5)
    c.setFillColor(MUTED)
    c.drawString(18 * mm, 10 * mm, "Hermes plugin account-pool 3.3.0 · github.com/roqianjas/hermes-account-pool")
    c.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Halaman {doc.page}")
    c.setStrokeColor(LINE)
    c.line(18 * mm, 14 * mm, A4[0] - 18 * mm, 14 * mm)
    c.restoreState()


# ── content ──────────────────────────────────────────────────────────────────
st += [Paragraph("Plugin account-pool: perintah <font name='Mono'>hermes account</font>", s_title),
       Paragraph("Dokumentasi lengkap versi 3.3.0: kelola akun di credential pool Hermes, bagi pemakaian akun "
                 "Claude secara merata, pantau sesi, pulihkan masalah otomatis, dan terima peringatan.", s_sub)]

H1("1. Ringkasan")
P("Semua perintah memakai pola yang sama, <b>provider dulu, baru aksi</b>:")
code("hermes account <provider> <action> [target] [options]")
table([
    ["Aksi", "Fungsi", "Mengubah?"],
    [C("list"), "Daftar akun dalam rotasi dan yang diparkir (beserta jadwal --until)", "Tidak"],
    [C("check"), "Kesehatan: mati, kena limit, cooling down, label salah, duplikat, email asli", "Tidak"],
    [C("usage"), "Pemakaian kuota 5 jam per akun, termasuk akun yang diparkir", "Tidak*"],
    [C("who"), "Sesi mana sedang memakai akun apa", "Tidak"],
    [C("report"), "Riwayat pemakaian: beban per akun, jam tersibuk, waktu semua akun penuh", "Tidak"],
    [C("add"), "Tambah akun: login, cek email asli, tolak duplikat, langsung diurutkan", "Ya"],
    [C("remove"), "Hapus login akun (termasuk akun yang diparkir), dengan konfirmasi", "Ya"],
    [C("park"), "Keluarkan akun dari rotasi tanpa hapus login; " + C("--until") + " untuk sementara", "Ya"],
    [C("unpark"), "Kembalikan akun yang diparkir ke rotasi", "Ya"],
    [C("relogin"), "Login ulang akun dengan verifikasi email, label dan posisi tetap", "Ya"],
    [C("balance"), "Urutkan akun, istirahatkan yang ≥ 90%, pulihkan otomatis, kirim peringatan", "Ya"],
    [C("doctor"), "Periksa seluruh setup dalam satu perintah", "Tidak"],
    [C("notify"), "Atur dan tes saluran peringatan (desktop, Telegram)", "Pengaturan"],
    [C("help"), "Bantuan lengkap", "Tidak"],
], [0.15, 0.67, 0.18])
P("* " + C("usage") + " memperbarui access token yang kedaluwarsa, sama seperti yang Hermes lakukan saat akun dipakai.")
H2("Dukungan provider")
table([
    ["Fitur", "Provider"],
    [C("list") + ", " + C("check") + ", " + C("park") + "/" + C("unpark") + " (+ " + C("--until") + "), " + C("who") + ", "
     + C("doctor") + ", peringatan login, pemulihan cooling down", "<b>Semua provider</b> di credential pool (OAuth dan API key)"],
    [C("relogin"), "Provider dengan login OAuth. Verifikasi email butuh adapter identity."],
    [C("usage") + ", " + C("report") + ", urutan " + C("balance") + ", peringatan \"semua akun tinggi\", email asli",
     "Provider yang punya <b>adapter</b>. Bawaan: <b>anthropic</b> (5 jam) dan <b>openai-codex</b> (5 jam + mingguan)."],
], [0.55, 0.45])
P("Kode khusus provider ada di " + C("providers.py") + " (adapter). Tanpa adapter, " + C("usage") + " dan " + C("report")
  + " menampilkan pesan jelas, dan " + C("balance") + " tetap menjalankan unpark terjadwal, pemulihan, dan "
  "peringatan login, tetapi urutan akun tidak diubah. Provider lain bisa ditambahkan dengan menulis satu adapter.")
P("<b>Codex</b>: balance memakai limit yang paling ketat di antara 5 jam dan mingguan, dan " + C("usage")
  + " menampilkan keduanya, misalnya " + C("5h 12% · week 78%") + ". Akun Codex yang juga login di Codex CLI atau VS Code "
  "berbagi kuota dengan aplikasi itu. Hermes memakai login Codex-nya sendiri dan tidak mengambil " + C("~/.codex/auth.json") + ".")
note("Plugin hanya mengelola akun <b>di dalam</b> satu provider. Apakah sebuah profil memakai provider itu (model utama, "
     "urutan fallback) tetap diatur di pengaturan Hermes. Provider yang belum punya akun cukup diam: "
     + C("hermes account openai-codex doctor") + " menyebutnya \"not in use\".")

H1("2. Setup yang disarankan")
table([
    ["Item", "Nilai"],
    ["Akun", "Beberapa akun Claude (Pro/Max/Team) login OAuth di profil default: " + C("hermes account anthropic add &lt;email&gt;")],
    ["Strategi akun (semua profil)", C("credential_pool_strategies.anthropic: fill_first")],
    ["Penjadwal", "systemd user timer, setiap 5 menit: " + C("hermes account anthropic balance")],
    ["Ambang istirahat", "90% kuota 5 jam"],
    ["Pelacak sesi", "Plugin " + C("account-pool-tracker") + " aktif di semua profil (untuk " + C("who") + ")"],
    ["Peringatan", "Notifikasi desktop (notify-send) + Telegram ke chat pribadi (TELEGRAM_ALLOWED_USERS)"],
    ["Fallback", "Jika semua akun tidak tersedia: fallback model yang Anda atur di Hermes"],
], [0.28, 0.72])
P("Setiap 5 menit penjadwal menjalankan lima langkah:")
LI(["Mengaktifkan lagi akun yang " + C("park --until") + "-nya sudah lewat.",
    "Mencoba ulang refresh token akun yang <b>COOLING DOWN</b> (gagal karena jaringan).",
    "Membaca pemakaian 5 jam, mengistirahatkan akun ≥ 90%, lalu mengurutkan akun dari yang paling longgar.",
    "Mencatat riwayat pemakaian (untuk " + C("report") + ").",
    "Mengirim peringatan jika ada masalah baru."])
P("Dengan " + C("fill_first") + ", setiap sesi baru mengambil akun teratas, yaitu yang paling longgar. "
  "Jika sebuah akun kena limit di tengah sesi, Hermes memindahkan sesi itu ke akun berikutnya.")

H1("3. Lokasi file")
table([
    ["File", "Isi"],
    [C("~/.hermes/plugins/account-pool/"), "Plugin utama (perintah " + C("hermes account") + "), versi 3.3.0; adapter di " + C("providers.py")],
    [C("~/.hermes/plugins/account-pool-tracker/"), "Pelacak sesi; di-symlink ke " + C("profiles/*/plugins/")],
    [C("~/.hermes/auth.json"), "Credential pool bersama semua profil"],
    [C("~/.hermes/account-pool-parked.json"), "Akun yang diparkir (berisi token)"],
    [C("~/.hermes/account-pool-sessions.json"), "Sesi dan akunnya, 24 jam terakhir (tanpa token)"],
    [C("~/.hermes/account-pool-history.jsonl"), "Riwayat pemakaian tiap 5 menit, sekitar 14 hari"],
    [C("~/.hermes/account-pool-alerts.json"), "Peringatan yang sudah terkirim (mencegah pesan berulang)"],
    [C("~/.hermes/account-pool.json"), "Pengaturan peringatan"],
    [C("~/.config/systemd/user/") + "<br/>" + C("hermes-account-balance.{service,timer}"), "Penjadwal 5 menit"],
], [0.50, 0.50])
note("Semua file data berizin 600. Plugin utama hanya dipasang di profil <b>default</b>, jadi profil bot lain tidak bisa "
     "mengubah akun. Pelacak di profil bot hanya mencatat label akun, tidak menambah perintah atau tool.")

H1("4. Bantuan (help)")
code("""
hermes account                 # semua cara ini menampilkan bantuan yang sama
hermes account help
hermes account --help
hermes account anthropic help
""")
P("Perintah atau opsi yang salah ditolak dengan pesan singkat dan exit code 2:")
table([
    ["Perintah", "Pesan"],
    [C("hermes account anthropic"), "Missing action for provider 'anthropic'."],
    [C("hermes account anthropic lst"), "'lst' is not an action. Did you mean: list?"],
    [C("hermes account anthropic park"), "Missing target. Usage: hermes account anthropic park &lt;email|id&gt;"],
    [C("hermes account anthropic list extra"), "'list' takes no target (got 'extra')."],
    [C("hermes account anthropic usage --hours 5"), "--hours only applies to: report"],
], [0.45, 0.55])

H1("5. Perintah satu per satu")
H2("5.1 list")
code("""
$ hermes account anthropic list
[anthropic] in rotation (5):
  #1  erin@example.com                   id=12e90b  status=ok
  ...
[anthropic] parked (1):
  -   dave@example.com                   id=e6dcdc  since 2026-10-10 12:56  until 2026-10-10 17:00
""")
H2("5.2 check")
code("""
$ hermes account anthropic check
[anthropic] in rotation: 6   parked: 0
  OK #1 id=12e90b  label=erin@example.com
        account : erin@example.com
  ...
  All accounts in rotation are healthy.
""")
table([
    ["Status", "Arti", "Tindakan"],
    ["DEAD", "Login ditolak Anthropic (refresh token tidak berlaku)", C("relogin") + " (bagian 5.8)"],
    ["RATE LIMITED", "Anthropic membalas 429/402", "Tunggu reset; Hermes memakai akun lain"],
    ["BENCHED by balance", "Diistirahatkan karena ≥ 90%", "Otomatis aktif lagi saat reset"],
    ["COOLING DOWN", "Refresh token gagal, biasanya jaringan putus", "Dipulihkan otomatis oleh penjadwal"],
    ["WRONG LABEL", "Label berbeda dari email asli", C("relogin") + " di jendela incognito"],
    ["DUPLICATE", "Akun yang sama terdaftar dua kali", C("hermes account anthropic remove &lt;id&gt;")],
], [0.22, 0.43, 0.35])
H2("5.3 usage")
code("""
$ hermes account anthropic usage
[anthropic] 5-hour usage
  account                            state     used                          resets
  -- in rotation --
  alice@example.com                  active      2%  [....................]  16:49
  bob@example.com                    active      3%  [....................]  17:00
  carol@example.com                  active     10%  [##..................]  17:10
  -- parked (not used by Hermes) --
  frank@example.com                  PARKED     30%  [======..............]  15:50
""")
P("Angkanya sama dengan \"Current session\" di pengaturan pemakaian claude.ai. Kolom state: " + C("active") + ", " + C("BENCHED")
  + " (diistirahatkan balance), " + C("LIMITED") + " (limit dari Anthropic), " + C("PARKED") + " (bar "
  + C("=") + "), dan " + C("DEAD") + ". Token akun yang diparkir diperbarui otomatis, lalu langsung disimpan "
  "ke file parkir karena refresh token Anthropic hanya bisa dipakai sekali.")
H2("5.4 who")
code("""
$ hermes account anthropic who
[anthropic] sessions active in the last 30 min: 2
  bob@example.com
      worker-bot           cli       20261010_125450_49cc18 claude-sonnet-5-5    0m ago
      default              cli       20261010_125434_294cbf claude-opus-5-5      0m ago
  erin@example.com        (idle)
  ...
$ hermes account anthropic who --minutes 120     # jendela waktu lain
""")
LI(["Data berasal dari plugin pelacak, yang mencatat setiap sesi setelah panggilan API ke model.",
    "Jika sesi pindah akun karena limit, muncul keterangan " + C("(moved from ...)") + ".",
    "Sesi yang sudah berjalan sebelum pelacak dipasang baru muncul setelah " + C("/reset") + ", atau setelah "
    "gateway/desktop di-restart."])
H2("5.5 report")
code("""
$ hermes account anthropic report               # 24 jam terakhir
$ hermes account anthropic report --hours 72
# contoh ILUSTRASI format (angka akan terisi setelah riwayat terkumpul):
[anthropic] usage report: last 24h (288 snapshots, 24.0h covered, from 10-10 13:00)
  'used' adds up 5-hour-window percent: 100 = one full 5-hour window.
  account                              used  share  peak  time >= 90%
  bob@example.com                       140    31%   92%        25 min
  ...
  Busiest hours: 09:00-10:00 (60), 14:00-15:00 (48), 10:00-11:00 (41)
  Time with EVERY account >= 90%: 0 min
""")
LI([C("used") + ": total kenaikan pemakaian. 100 berarti setara satu jendela 5 jam penuh.",
    C("time ≥ 90%") + ": berapa lama akun hampir habis.",
    "Jika <b>semua akun ≥ 90%</b> pernah terjadi, laporan menyarankan menambah akun.",
    "Saran baru muncul setelah ada data minimal 2 jam dengan pemakaian nyata."])
H2("5.6 park / unpark")
code("""
$ hermes account anthropic park frank@example.com                     # sampai di-unpark
$ hermes account anthropic park frank@example.com --until 17:00
$ hermes account anthropic park frank@example.com --until +2h  # juga: 90m, 1d
$ hermes account anthropic unpark frank@example.com
""")
LI([C("park") + " menerima email, nomor urut, atau id. Akun aktif terakhir tidak bisa diparkir.",
    "Dengan " + C("--until") + ", akun aktif lagi pada putaran penjadwal pertama setelah waktunya "
    "(paling lambat 5 menit). Jam yang sudah lewat hari ini berarti besok.",
    "Gunanya, misalnya, menyisakan kuota akun tertentu untuk Anda pakai sendiri di claude.ai."])
H2("5.7 balance")
code("""
$ hermes account anthropic balance --dry-run       # rencana saja
$ hermes account anthropic balance                 # jalankan (otomatis tiap 5 menit)
2026-10-10 12:56:06 [anthropic] balance:
  - unpark dave@example.com (park --until 2026-10-10 12:57 reached)
  - recovered: erin@example.com (token refresh retried)
  - order: erin(4%) > bob(5%) > alice(5%) > carol(10%) > frank(30%)
""")
H2("5.8 relogin")
code("""
$ hermes account anthropic relogin alice@example.com
Re-login alice@example.com (anthropic, id=0b1e86)
  1. A browser sign-in link opens. Use a PRIVATE / INCOGNITO window,
     otherwise the browser may sign in as a different account.
  2. Sign in as: alice@example.com
  3. Paste the code back here.
The old entry is replaced only if the new sign-in really is that account.
Continue? [y/N]
""")
LI(["Login baru ditambahkan <b>dulu</b>, lalu email aslinya dicek.",
    "Jika emailnya cocok, entri lama dihapus dan entri baru menempati posisi yang sama.",
    "Jika emailnya berbeda (browser login ke akun lain), login baru dibuang dan entri lama tidak disentuh.",
    "Akun yang sedang diparkir harus di-" + C("unpark") + " dulu. " + C("--yes") + " melewati konfirmasi."])
H2("5.9 doctor")
code("""
$ hermes account anthropic doctor
[anthropic] doctor
  OK    strategy fill_first in 6 profiles
  OK    every profile uses the shared account pool
  OK    session tracker active in every profile
  OK    auth.json permissions 600
  OK    account-pool-parked.json permissions 600
  OK    balance timer active, last run 2026-10-10 12:53:08 WIB
  OK    usage history last written 2 min ago
  OK    6 accounts in rotation, 0 parked
  OK    usage endpoint reachable
  OK    alert channels: desktop, telegram via default
  0 failure(s), 0 warning(s).
""")
P("Jalankan setelah update Hermes atau saat bot berperilaku aneh. Setiap baris FAIL menyertakan perintah "
  "perbaikannya. Exit code 1 jika ada FAIL.")
H2("5.10 notify")
code("""
hermes account anthropic notify                      # status
hermes account anthropic notify test                 # kirim pesan tes
hermes account anthropic notify desktop-off          # / desktop-on
hermes account anthropic notify telegram-off         # / telegram-on
hermes account anthropic notify telegram-via=default # bot profil mana yang mengirim
""")
table([
    ["Peringatan", "Kapan", "Dikirim"],
    ["<b>Akun perlu login ulang</b>", "Sebuah akun berstatus DEAD", "Sekali per akun"],
    ["<b>Semua akun di atas 80%</b>", "Setiap akun dalam rotasi ≥ 80%", "Sekali, lalu kabar saat pulih"],
], [0.32, 0.40, 0.28])
note("Telegram dikirim lewat " + C("hermes send") + " ke user pertama di " + C("TELEGRAM_ALLOWED_USERS")
     + ", memakai bot profil default. Jika bot default belum diatur, pakai bot profil lain: "
     + C("notify telegram-via=&lt;profil&gt;") + ".")

H1("6. Cara kerja balance")
LI(["Akun <b>DEAD</b> dilewati dan ditaruh paling bawah.",
    "Akun ≥ ambang diistirahatkan sampai jam reset-nya (ditandai " + C("[account-pool]") + "), dan dilepas "
    "lagi saat turun. Limit asli dari Anthropic tidak disentuh.",
    "Akun diurutkan dari pemakaian terendah. Akun yang pemakaiannya tidak terbaca ditaruh setelah akun sehat.",
    "<b>Pengaman:</b> jika semua akun ≥ ambang, hanya akun yang 100% yang diistirahatkan.",
    "Jika pemakaian tidak bisa dibaca sama sekali, urutan tidak diubah. Pemulihan dan unpark tetap jalan."])
note("Balance butuh strategi " + C("fill_first") + ". Dengan " + C("round_robin") + ", urutannya diacak "
     "setiap sesi baru. " + C("doctor") + " mengecek ini di keenam profil.")

H1("7. Timer otomatis")
code("""
systemctl --user list-timers hermes-account-balance.timer          # status, jadwal berikutnya
journalctl --user -u hermes-account-balance.service -n 20 -o cat   # log
systemctl --user start hermes-account-balance.service              # jalankan sekarang
systemctl --user disable --now hermes-account-balance.timer        # matikan
systemctl --user enable --now hermes-account-balance.timer         # nyalakan
""")
P("Interval: " + C("systemctl --user edit --full hermes-account-balance.timer") + " (" + C("OnUnitActiveSec")
  + "). Ambang: tambahkan " + C("--threshold 85") + " di baris " + C("ExecStart") + " pada file service, lalu "
  + C("systemctl --user daemon-reload") + ". Timer tidak memakai token AI.")

H1("8. Pindah akun otomatis bawaan Hermes")
table([
    ["Kondisi dari Anthropic", "Tindakan Hermes", "Akun diistirahatkan"],
    ["429 rate limit", "Coba ulang 1x (menunggu sampai 600 detik), lalu pindah. Langsung pindah jika akun "
     "sudah berstatus limit/benched", "Sampai reset, atau 1 jam"],
    ["\"usage limit reached\"", "Langsung pindah", "Sampai reset"],
    ["402 / billing", "Langsung pindah", "1 jam"],
    ["401 token kedaluwarsa", "Refresh token, tidak pindah", "5 menit jika refresh gagal"],
    ["Refresh token ditolak", "Akun DEAD, keluar dari rotasi", "Sampai login ulang"],
], [0.25, 0.47, 0.28])
P("Ambang 90% di balance membuat akun diistirahatkan sebelum penuh, sehingga sesi baru tidak macet menunggu 600 detik.")

H1("9. Tambah dan hapus akun")
code("""
$ hermes account anthropic add name@example.com
Add name@example.com to anthropic
  1. A browser sign-in link opens. Use a PRIVATE / INCOGNITO window,
     otherwise the browser may sign in as an account that is already in the pool.
  2. Sign in as: name@example.com
  3. Paste the code back here.
  The account is kept only if the sign-in really is that account and not a duplicate.
Continue? [y/N] y
...
Verified: name@example.com
Added name@example.com (id=4f1c2a) to anthropic.
Balanced now: ...

$ hermes account anthropic remove name@example.com          # minta konfirmasi
""")
LI(["Jalankan dari profil <b>default</b> (tanpa " + C("-p") + "). Akun langsung dipakai semua profil.",
    "Setelah login, email asli dicek. Jika browser ternyata login ke akun lain, atau ke akun yang <b>sudah ada</b> "
    "di pool (termasuk yang labelnya salah), login itu dibuang dan pool tidak berubah.",
    "Email yang sudah ada di rotasi atau sedang diparkir ditolak, dengan petunjuk " + C("relogin") + " atau "
    + C("unpark") + ".",
    "Akun baru langsung masuk urutan " + C("balance") + ", tanpa menunggu timer.",
    C("remove") + " menolak menghapus akun aktif terakhir, dan bisa menghapus akun yang sedang diparkir. Untuk "
    "keluar sementara, pakai " + C("park") + ".",
    C("add --key") + " untuk provider atau akun berbasis API key (key diminta tanpa ditampilkan).",
    "Jangan pakai " + C("hermes -p &lt;profil&gt; auth add") + ": profil itu akan punya pool sendiri. "
    + C("doctor") + " mendeteksinya.",
    "Jangan berbagi token Hermes dengan aplikasi atau perangkat lain. Refresh token sekali pakai, jadi berbagi token "
    "bisa membuat salah satu login mati."])

H1("10. Memaksa akun tertentu")
code("""
# Cara 1: parkir akun yang tidak ingin dipakai (bisa sementara)
hermes account anthropic park frank@example.com --until 17:00

# Cara 2: matikan balance, atur urutan manual, nyalakan lagi nanti
systemctl --user disable --now hermes-account-balance.timer
hermes auth priority anthropic bob@example.com 0
systemctl --user enable --now hermes-account-balance.timer
""")

H1("11. Batasan")
LI(["<b>Sesi yang berjalan tidak dipindah</b> sebelum akunnya kena limit. Pindah di tengah sesi menghapus "
    "prompt cache dan memboroskan token.",
    "Endpoint " + C("/api/oauth/usage") + " dan " + C("/api/oauth/profile") + " <b>tidak didokumentasikan "
    "resmi</b>. Jika berubah, " + C("usage") + "/" + C("balance") + "/" + C("report") + " berhenti mengubah "
    "urutan; pindah otomatis bawaan Hermes tetap jalan, dan " + C("doctor") + " menandainya FAIL.",
    "Kuota mingguan akun Team tidak tersedia dari endpoint ini.",
    C("who") + " mencari sesi lewat stack thread yang sedang berjalan. Jika suatu update Hermes mengubah "
    "struktur internalnya, " + C("who") + " kosong tetapi bot tidak terganggu (pelacak menelan semua error).",
    C("relogin") + " membutuhkan terminal interaktif untuk menempel kode login.",
    "Adapter usage ada untuk anthropic dan openai-codex (endpoint " + C("chatgpt.com/backend-api/wham/usage")
    + ", juga tidak resmi). Adapter Codex baru diuji read-only pada akun asli; " + C("add") + " dengan login Codex "
    "sungguhan belum pernah dijalankan. Perintah umum untuk provider lain baru dites dengan akun API key."])

H1("12. Troubleshooting")
table([
    ["Gejala", "Penyebab umum", "Solusi"],
    ["Bot \"retrying in 600s\"", "Akun kena 429 sebelum balance mengistirahatkannya",
     C("hermes account anthropic balance") + ", lalu stop dan kirim ulang pesan"],
    ["check: DEAD", "Login dicabut atau token dipakai aplikasi lain", C("hermes account anthropic relogin &lt;email&gt;")],
    [C("who") + " kosong", "Sesi dimulai sebelum pelacak dipasang", C("/reset") + " sesi, atau restart gateway/desktop"],
    ["Tidak ada pesan Telegram", "Token bot tidak valid", C("notify test") + "; ganti " + C("telegram-via")],
    [C("report") + ": not enough history", "Timer mati atau baru dipasang", C("doctor")],
    ["Akun --until tidak kembali", "Timer mati", C("systemctl --user enable --now hermes-account-balance.timer")],
    [C("hermes account") + " tidak dikenal", "Dijalankan dengan -p (plugin hanya di default)", "Jalankan tanpa -p"],
], [0.25, 0.37, 0.38])

H1("13. Referensi cepat")
table([
    ["Kebutuhan", "Perintah"],
    ["Bantuan", C("hermes account help")],
    ["Cek semua setup", C("hermes account anthropic doctor")],
    ["Kesehatan akun", C("hermes account anthropic check")],
    ["Pemakaian 5 jam", C("hermes account anthropic usage")],
    ["Siapa pakai akun apa", C("hermes account anthropic who")],
    ["Laporan 3 hari", C("hermes account anthropic report --hours 72")],
    ["Parkir sementara", C("hermes account anthropic park &lt;email&gt; --until 17:00")],
    ["Aktifkan lagi", C("hermes account anthropic unpark &lt;email&gt;")],
    ["Tambah akun", C("hermes account anthropic add &lt;email&gt;")],
    ["Hapus akun", C("hermes account anthropic remove &lt;email&gt;")],
    ["Login ulang", C("hermes account anthropic relogin &lt;email&gt;")],
    ["Seimbangkan sekarang", C("hermes account anthropic balance")],
    ["Tes peringatan", C("hermes account anthropic notify test")],
    ["Log timer", C("journalctl --user -u hermes-account-balance.service -n 20 -o cat")],
], [0.30, 0.70])

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hermes-account-pool.pdf")
os.makedirs(os.path.dirname(out), exist_ok=True)
SimpleDocTemplate(out, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=20 * mm,
                  title="Hermes account-pool plugin", author="github.com/roqianjas/hermes-account-pool").build(st, onFirstPage=footer,
                                                                                    onLaterPages=footer)
print(out)
