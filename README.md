# kscli — Kuaishou CLI Automation Engine

CLI automation cho Kuaishou trên MuMu Player Pro (macOS).

## Cài đặt

```bash
pip install git+https://github.com/mun0602/kscli.git
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

# Thêm --json để lấy output JSON
dk list --json
dk stats --json
```

## Yêu cầu

- macOS (Apple Silicon)
- MuMu Player Pro
- Python >= 3.9
