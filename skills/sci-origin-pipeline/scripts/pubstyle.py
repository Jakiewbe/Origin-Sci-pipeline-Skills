"""pubstyle.py - 论文级配图工具包 (matplotlib)。
由对比"用户手工精修的 Origin 图"与"早期代码出图"总结而来。
核心原则见 ../references/publication_visual_and_origin_craft.md。用法:
    import pubstyle as ps
    ps.setup()
    fig, ax = plt.subplots(figsize=(8.8, 6.8)); ps.minimal_axes(ax)
"""
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from matplotlib.colors import to_rgb, LinearSegmentedColormap

# 1) 调色板: 同色系明暗成对, 冷色(蓝)=对照/常规, 暖色(红)=脉冲/处理; 避免彩虹色
PALETTE = {
    "ice": "#C5DBF5", "blue": "#3E86DE", "rose": "#D84B5C",
    "pink": "#E8A3AF", "wine": "#A02333", "indigo": "#6579BE",
}
GUIDE_D, GUIDE_G = PALETTE["pink"], PALETTE["blue"]   # 辅助线与标签同色


def setup(font="Times New Roman"):
    plt.rcParams.update({
        "font.family": font, "font.weight": "bold", "mathtext.fontset": "stix",
        "axes.linewidth": 3.0, "axes.labelweight": "bold",
        "savefig.dpi": 300, "figure.dpi": 150,
    })


def mix(color, other="#FFFFFF", t=0.45):
    a, b = np.array(to_rgb(color)), np.array(to_rgb(other))
    return tuple(a * (1 - t) + b * t)


def luminance(color):
    r, g, b = to_rgb(color)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def minimal_axes(ax, x_major=None, show_y_ticks=False, label_size=24):
    """四周 3pt 边框; 只保留底轴主刻度(朝内); 无次刻度; 默认无 y 刻度。"""
    for sp in ax.spines.values():
        sp.set_linewidth(3.0)
    ax.xaxis.set_minor_locator(ticker.NullLocator())
    ax.yaxis.set_minor_locator(ticker.NullLocator())
    if x_major:
        ax.xaxis.set_major_locator(ticker.MultipleLocator(x_major))
        ax.xaxis.set_major_formatter(ticker.FormatStrFormatter("%d"))
    ax.tick_params(axis="x", direction="in", length=7, width=2.5, top=False,
                   bottom=True, labelsize=label_size, pad=8)
    if show_y_ticks:
        ax.tick_params(axis="y", direction="in", length=7, width=2.5, right=False,
                       labelsize=label_size, pad=7)
    else:
        ax.set_yticks([])


def gradient_bar(ax, x, height, width, color, bottom_color=None, edge="#222222",
                 lw=1.2, zorder=3):
    """竖向渐变柱: 顶部=主色, 底部=变浅(深色柱)或变深(浅色柱), 质感来源之一。"""
    if bottom_color is None:
        bottom_color = mix(color, "#FFFFFF", 0.45) if luminance(color) < 0.72 \
            else mix(color, PALETTE["blue"], 0.35)
    cmap = LinearSegmentedColormap.from_list("g", [bottom_color, color])
    grad = np.linspace(0, 1, 256).reshape(-1, 1)
    x0, x1 = x - width / 2, x + width / 2
    im = ax.imshow(grad, extent=(x0, x1, 0, height), origin="lower", cmap=cmap,
                   aspect="auto", zorder=zorder, interpolation="bilinear")
    rect = plt.Rectangle((x0, 0), width, height, fill=False, ec=edge, lw=lw, zorder=zorder + 1)
    ax.add_patch(rect)
    return im


def value_labels(ax, xs, tops, texts, colors, size=22, pad=0.03):
    """数值标签: 加粗、放大、与柱同色(浅色柱可加深一档保证可读)。"""
    for x, t, s, c in zip(xs, tops, texts, colors):
        c = c if luminance(c) < 0.8 else mix(c, "#000000", 0.18)
        ax.text(x, t + pad, s, ha="center", va="bottom", fontsize=size,
                fontweight="bold", color=c)


def guide_lines(ax, xs_colors, lw=2.8):
    """贯穿式虚线 (与谱线等粗), 颜色与对应标签一致。"""
    for x, c in xs_colors:
        ax.axvline(x, color=c, ls=(0, (4, 2.2)), lw=lw, zorder=1)


def peak_tag(ax, x, y, text, color, size=22, dx=0):
    """标签贴着峰肩, 而不是悬在顶部; 与导线同色。"""
    ax.text(x + dx, y, text, color=color, fontsize=size, fontweight="bold",
            ha="center", va="center")


def corner_legend(ax, handles=None, size=18.5):
    """左上角、无边框、线段样图例, 利用基线空白区。"""
    return ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.012, 0.985),
                     frameon=False, handlelength=1.5, handletextpad=0.45,
                     borderaxespad=0.2, prop={"weight": "bold", "size": size})


def stack(curves, gap):
    """瀑布堆叠: 每条曲线归一化后按 gap 垂直平移; 返回平移后的 y 列表。"""
    return [y + i * gap for i, y in enumerate(curves)]
