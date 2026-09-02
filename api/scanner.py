import cv2  # library pengolahan gambar OpenCV
import numpy as np  # library numerik untuk operasi array

# konstanta tinggi maksimal gambar setelah di-resize
tinggi_maks = 800  # batas maksimum tinggi dalam pixel


def scan_image(image_bytes: bytes) -> bytes:
    """Ubah foto Telegram menjadi bersih:
    1. Decode ke OpenCV
    2. Grayscale (cvtColor)
    3. Reduksi noise (GaussianBlur)
    4. Adaptive threshold -> hitam-putih
    5. Encode kembali ke JPEG dan kembalikan bytes.
    """
    # 1. Decode bytes gambar ke array OpenCV
    nparr = np.frombuffer(image_bytes, np.uint8)  # ubah bytes jadi array numerik uint8
    img = cv2.imdecode(
        nparr, cv2.IMREAD_COLOR
    )  # decode array ke citra OpenCV warna (BGR)

    if img is None:
        raise ValueError("Gambar tidak valid atau gagal di-decode")
    
    # buat benerin error rasio    
    img_asli = img.copy()

    # jika resolusi gambar terlalu besar turunkan
    h_asli, w_asli = img.shape[:2]  # ambil tinggi dan lebar asli gambar
    rasio = 1.0  # inisialisasi rasialisasi 1.0 (tidak di-resize)
    if h_asli > tinggi_maks:  # jika gambar lebih tinggi dari batas maks
        rasio = img.shape[0] / float(tinggi_maks)  # hitung faktor pengurangi tinggi
        img = cv2.resize(
            img, (int(img.shape[1] / rasio), tinggi_maks)
        )  # resize lebar seperlimal tinggi

    # ubah jadi grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)  # konversi citra warna ke grayscale

    # blur
    blur = cv2.GaussianBlur(
        gray, (5, 5), 0
    )  # smooth gambar dengan Gaussian Blur kernel 5x5

    # edged
    edged = cv2.Canny(blur, 75, 200)  # deteksi tepi menggunakan Canny threshold 75-200

    # dilasi tipis: menyambung tepi yang terputus putus supaya kontur
    # dokumen menjadi utuh
    kernel = np.ones((3, 3), np.uint8)  # kernel struktur elemen dilasi 3x3
    edged = cv2.dilate(
        edged, kernel, iterations=1
    )  # melapisi tepi untuk menyambungkan kontur putus

    kontur, _ = cv2.findContours(
        edged.copy(), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE
    )  # cari semua kontur di citra edged
    kontur = sorted(kontur, key=cv2.contourArea, reverse=True)[
        :5
    ]  # urutkan kontur berdasarkan luas, ambil 5 terbesar

    h, w = img.shape[:2]  # ambil tinggi dan lebar setelah resize (jika ada)
    toleransi_tepi = 10  # piksel, untuk anggap "menyentuh" tepi bawah  # toleransi 10 pixel untuk deteksi tepi bawah

    titik_sudut = None  # variabel untuk menyimpan 4 sudut dokumen

    # --- Coba cara normal dulu: cari kontur yang persis 4 titik ---
    for c in kontur:  # iterasi tiap kontur terbesar
        keliling = cv2.arcLength(c, True)  # hitung keliling kontur
        approx = cv2.approxPolyDP(
            c, 0.02 * keliling, True
        )  # pendekatan poligon dengan toleransi 2% dari keliling
        if len(approx) == 4:  # jika ada 4 titik (persegi/persegi panjang)
            titik_sudut = approx.reshape(4, 2)  # simpan 4 titik sudut
            break  # keluar dari loop

    # --- Kalau gagal, cek apakah kontur terbesar "menyentuh" tepi bawah gambar ---
    if (
        titik_sudut is None and len(kontur) > 0
    ):  # jika tidak ditemukan 4 titus tapi ada kontur
        hull = cv2.convexHull(kontur[0])  # hitung convex hull dari kontur terbesar
        kontur_terbesar = hull.reshape(-1, 2)  # ubah bentuk menjadi array titik 2D
        y_maks = kontur_terbesar[:, 1].max()  # titik tertinggi pada sumbu Y
        menyentuh_bawah = y_maks >= (
            h - 1 - toleransi_tepi
        )  # apakah kontur menyentuh tepi bawah (dengan toleransi)

        if menyentuh_bawah:  # jika menyentuh tepi bawah
            y_tengah = h / 2  # garis tengah gambar secara vertikal
            titik_atas = kontur_terbesar[
                kontur_terbesar[:, 1] < y_tengah
            ]  # titik di atas tengah
            titik_bawah = kontur_terbesar[
                kontur_terbesar[:, 1] >= y_tengah
            ]  # titik di bawah atau pada tengah

            if (
                len(titik_atas) > 0 and len(titik_bawah) > 0
            ):  # pastikan ada titik di keduanya
                s_atas = (
                    titik_atas[:, 0] + titik_atas[:, 1]
                )  # jumlah x+y untuk setiap titik Atas
                diff_atas = (
                    titik_atas[:, 0] - titik_atas[:, 1]
                )  # perbedaan x-y untuk titik Atas

                top_left = titik_atas[
                    np.argmin(s_atas)
                ]  # titik kiri atas (x+y terkecil)
                top_right = titik_atas[
                    np.argmax(diff_atas)
                ]  # titik kanan atas (x-y terkecil)

                bottom_left_x = titik_bawah[np.argmin(titik_bawah[:, 0])][
                    0
                ]  # lebar kiri bawah
                bottom_right_x = titik_bawah[np.argmax(titik_bawah[:, 0])][
                    0
                ]  # lebar kanan bawah

                bottom_left = np.array(
                    [bottom_left_x, h - 1]
                )  # titik kiri bawah (dipotong ke bawah)
                bottom_right = np.array(
                    [bottom_right_x, h - 1]
                )  # kanan bawah (dipotong ke bawah)

                titik_sudut = np.array(
                    [top_left, top_right, bottom_right, bottom_left]
                )  # susun ulang 4 sudut
                print(
                    "Sisi bawah dokumen terpotong frame, tepi bawah gambar dipakai sebagai pengganti."
                )  # catatan log

    # --- Fallback terakhir: pakai seluruh frame ---
    if titik_sudut is None:  # jika tidak ditemukan pun sudut punapa
        print(
            "Kontur 4 sisi tidak ditemukan, fallback pakai seluruh frame."
        )  # catatan log
        titik_sudut = np.array(
            [[0, 0], [w, 0], [w, h], [0, h]]
        )  # gunakan seluruh frame sebagai ROI

    def urutkan_titik(pts):
        """Urutkan 4 titik jadi: top-left, top-right, bottom-right, bottom-left."""
        rect = np.zeros(
            (4, 2), dtype="float32"
        )  # array kosong untuk menampung 4 titur urut

        s = pts.sum(axis=1)  # hitung x+y untuk setiap titik
        rect[0] = pts[np.argmin(s)]  # top-left     -> titik dengan x+y terkecil
        rect[2] = pts[np.argmax(s)]  # bottom-right -> titik dengan x+y terbesar

        diff = np.diff(pts, axis=1)  # hitung x-y untuk setiap titik
        rect[1] = pts[np.argmin(diff)]  # top-right -> titik dengan x-y terkecil
        rect[3] = pts[np.argmax(diff)]  # bottom-left -> titik dengan x-y terbesar

        return rect  # kembalikan array 4 titur terurut

    def perspective_transform(image, pts):
        rect = urutkan_titik(pts)  # urutkan 4 titik sudut ke format standar
        tl, tr, br, bl = (
            rect  # pecah ke 4 titik: kiri atas, kanan atas, kanan bawah, kiri bawah
        )

        lebar_bawah = np.linalg.norm(br - bl)  # hitung panjang sisi kiri bawah
        lebar_atas = np.linalg.norm(tr - tl)  # hitung panjang sisi atas
        lebar_maks = int(
            max(lebar_bawah, lebar_atas)
        )  # lebar maksimum dari atas dan bawah

        tinggi_kanan = np.linalg.norm(tr - br)  # hitung tinggi kanan
        tinggi_kiri = np.linalg.norm(tl - bl)  # hitung tinggi kiri
        tinggi_maks = int(max(tinggi_kanan, tinggi_kiri))  # tinggi maksimum

        dst = np.array(
            [  # titik tujuan untuk pemetaan perspektif
                [0, 0],  # kiri atas
                [lebar_maks - 1, 0],  # kanan atas
                [lebar_maks - 1, tinggi_maks - 1],  # kanan bawah
                [0, tinggi_maks - 1],  # kiri bawah
            ],
            dtype="float32",
        )

        M = cv2.getPerspectiveTransform(
            rect, dst
        )  # hitung matriks transformasi perspektif
        hasil = cv2.warpPerspective(
            image, M, (lebar_maks, tinggi_maks)
        )  # terapkan transformasi
        return hasil  # kembalikan gambar setelah transformasi

    # Skala titik sudut balik ke ukuran gambar asli (bukan yang sudah di-resize)
    titik_sudut_asli = (
        titik_sudut.astype("float32") * rasio
    )  # kalikan koordinat sudut dengan rasio resize

    hasil_warna = perspective_transform(
        img_asli, titik_sudut_asli
    )  # terapkan transformasi perspektif ke citra asli

    hasil_gray = cv2.cvtColor(
        hasil_warna, cv2.COLOR_BGR2GRAY
    )  # konversi hasil warna ke grayscale lagi (sekaligus memastikan format)

    # 3.  Adaptive threshold -> hasil hitam-putih bersih
    scanned = cv2.adaptiveThreshold(
        hasil_gray,  # citra grayscale input
        255,  # nilai maksimum pixel output
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,  # metode adaptif Gaussian-weighted sum
        cv2.THRESH_BINARY,  # threshold binary (0 atau 255)
        25,  # ukuran blok adaptif
        7,  # konstanta C dikurangi dari mean
    )

    # test otsu thresholding
    # ret, scanned = cv2.threshold(
    #     smoothed, 0, 255,
    #     cv2.THRESH_BINARY + cv2.THRESH_OTSU
    # )

    # 4. Cleanup akhir 
    # ojo nggo iki lek rusak
    # final = cv2.medianBlur(
    #     scanned, 3
    # )  # blur median 3x3 untuk menghilangkan noise pepper-and-salt
    final = scanned

    # 5. Encode menjadi PNG bytes
    ok, enc = cv2.imencode(".png", final)  # encode citra jadi format PNG
    if not ok:  # jika encode gagal
        raise RuntimeError("Gagal meng-encode gambar hasil scan")  # tampilkan error

    return enc.tobytes()  # kembalikan hasil sebagai bytes PNG
