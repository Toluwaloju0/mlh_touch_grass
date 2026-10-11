"""Small p4a Kivy recipe adjustment for Android cross-compilation."""

from pythonforandroid.recipes.kivy import KivyRecipe as UpstreamKivyRecipe


class KivyRecipe(UpstreamKivyRecipe):
    patches = UpstreamKivyRecipe.patches + ["android-skip-host-sdl2-probe.patch"]


recipe = KivyRecipe()
