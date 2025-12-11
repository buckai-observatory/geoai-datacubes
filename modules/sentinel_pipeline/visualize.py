# visualize.py
import matplotlib.pyplot as plt

def show_image(image, title="Image", cmap="gray"):
    """
    Displays an image with a title.
    """
    plt.figure(figsize=(8, 6))
    plt.imshow(image, cmap=cmap)
    plt.title(title)
    plt.axis("off")
    plt.show()
