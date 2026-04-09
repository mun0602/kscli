# kscli — Kuaishou CLI Automation Engine

CLI automation cho Kuaishou trên MuMu Player Pro (macOS).

## Cài đặt

```bash
# macOS / Linux
pip3 install git+https://github.com/mun0602/kscli.git

# Nếu "pip3 not found" → cài Python trước:
# brew install python3
```

> ⚠️ Sau khi cài xong, nếu lệnh `dk` không chạy được, thêm PATH:
> ```bash
> echo 'export PATH="$HOME/Library/Python/3.9/bin:$HOME/.local/bin:$PATH"' >> ~/.zshrc
> source ~/.zshrc
> ```

## Thiết lập 5SIM (lần đầu)

```bash
# Lấy token tại https://5sim.net/ → Profile → API Key
dk 5sim set-token <YOUR_TOKEN>

# Kiểm tra
dk 5sim           # Xem số dư
dk 5sim prices    # Xem giá SĐT
```

## Sử dụng

```bash
# Quản lý VM
dk list                    # Liệt kê VM
dk boot --vm 0             # Boot VM
dk stop --vm 0             # Tắt VM

# Farm
dk tuongtac --vm 0         # Xem video + tương tác
dk ketban --vm 0 --count 3 # Kết bạn
dk nuoinick --vm 0         # Nuôi nick nhẹ
dk run-session --vm 0      # Phiên farm đầy đủ

# Quản lý app
dk install-all             # Cài Kuaishou lên tất cả VM
dk check-app --vm 0        # Kiểm tra đã cài chưa

# Login
dk dangnhap --vm 0         # Auto login qua 5SIM

# 5SIM SMS
dk 5sim                    # Số dư
dk 5sim prices             # Bảng giá
dk 5sim buy                # Mua số mới
dk 5sim check --order 123  # Check SMS
dk 5sim cancel --order 123 # Hủy order

# Thêm --json để lấy output JSON
dk --json list
dk --json 5sim balance
```

## Yêu cầu

- macOS (Apple Silicon)
- MuMu Player Pro
- Python >= 3.9
