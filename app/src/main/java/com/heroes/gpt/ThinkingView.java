package com.heroes.gpt;

import android.animation.AnimatorSet;
import android.animation.ObjectAnimator;
import android.animation.ValueAnimator;
import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.util.AttributeSet;
import android.view.View;
import android.view.animation.LinearInterpolator;
import android.view.animation.OvershootInterpolator;

/**
 * مؤشر التفكير الاحترافي 💭
 * دوران 360° هادئ + حركة طفو جيبية (أعلى/أسفل) بمعدل 60fps،
 * مع ظهور واختفاء متدرجين ناعمين (fade in/out).
 */
public class ThinkingView extends View {

    private static final long ROTATE_MS = 4200;   // دورة دوران هادئة
    private static final long FLOAT_MS = 2600;    // دورة الطفو الجيبي
    private static final long FADE_MS = 260;      // مدة الظهور/الاختفاء

    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private float rotationDeg = 0f;
    private float floatOffset = 0f;
    private float alphaScale = 0f;   // 0..1
    private String glyph = "💭";
    private float textSizeSp = 34f;

    private ObjectAnimator rotateAnim;
    private ValueAnimator floatAnim;
    private ObjectAnimator fadeAnim;
    private boolean running = false;

    public ThinkingView(Context c) { this(c, null); }

    public ThinkingView(Context c, AttributeSet a) {
        super(c, a);
        paint.setTextSize(textSizeSp * getResources().getDisplayMetrics().density);
        paint.setTextAlign(Paint.Align.CENTER);
        paint.setColor(Color.WHITE);
        setLayerType(LAYER_TYPE_HARDWARE, null);
    }

    public void setGlyph(String g) {
        glyph = g == null || g.isEmpty() ? "💭" : g;
        invalidate();
    }

    /** يبدأ العرض مع fade-in ناعم — آمن للاستدعاء المتكرر. */
    public void start() {
        if (running) return;
        running = true;
        setVisibility(VISIBLE);

        rotateAnim = ObjectAnimator.ofFloat(this, "rotationDeg", 0f, 360f);
        rotateAnim.setDuration(ROTATE_MS);
        rotateAnim.setRepeatCount(ValueAnimator.INFINITE);
        rotateAnim.setInterpolator(new LinearInterpolator());

        floatAnim = ValueAnimator.ofFloat(0f, 1f);
        floatAnim.setDuration(FLOAT_MS);
        floatAnim.setRepeatCount(ValueAnimator.INFINITE);
        floatAnim.setRepeatMode(ValueAnimator.REVERSE);
        floatAnim.setInterpolator(new LinearInterpolator());
        floatAnim.addUpdateListener(a -> {
            float t = (float) a.getAnimatedValue();
            // موجة جيبية ناعمة: ±35% من نصف الارتفاع
            floatOffset = (float) Math.sin(t * Math.PI) * getHeight() * 0.28f;
            invalidate();
        });

        fadeAnim = ObjectAnimator.ofFloat(this, "alphaScale", 0f, 1f);
        fadeAnim.setDuration(FADE_MS);
        fadeAnim.setInterpolator(new OvershootInterpolator(0.6f));

        rotateAnim.start();
        floatAnim.start();
        fadeAnim.start();
    }

    /** يوقف العرض مع fade-out ناعم. */
    public void stop() {
        if (!running) { setVisibility(GONE); return; }
        running = false;
        if (rotateAnim != null) rotateAnim.cancel();
        if (floatAnim != null) floatAnim.cancel();
        ObjectAnimator out = ObjectAnimator.ofFloat(this, "alphaScale", alphaScale, 0f);
        out.setDuration(FADE_MS);
        out.addListener(new android.animation.AnimatorListenerAdapter() {
            @Override public void onAnimationEnd(android.animation.Animator a) {
                setVisibility(GONE);
                invalidate();
            }
        });
        out.start();
    }

    public boolean isRunning() { return running; }

    /** يستدعيه نظام الرسم لضبط الحجم النصي حسب الحجم الفعلي للعرض. */
    @Override
    protected void onSizeChanged(int w, int h, int ow, int oh) {
        super.onSizeChanged(w, h, ow, oh);
        paint.setTextSize(Math.min(h, w) * 0.62f);
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        if (alphaScale <= 0.01f) return;
        float cx = getWidth() / 2f;
        float cy = getHeight() / 2f;
        paint.setAlpha((int) (255 * alphaScale));
        canvas.save();
        canvas.translate(cx, cy + floatOffset);
        canvas.rotate(rotationDeg);
        canvas.drawText(glyph, 0, paint.getTextSize() / 3f, paint);
        canvas.restore();
    }

    @Override
    protected void onDetachedFromWindow() {
        super.onDetachedFromWindow();
        if (rotateAnim != null) rotateAnim.cancel();
        if (floatAnim != null) floatAnim.cancel();
        if (fadeAnim != null) fadeAnim.cancel();
        running = false;
    }

    // ===== used by ObjectAnimator =====
    public float getRotationDeg() { return rotationDeg; }
    public void setRotationDeg(float v) { rotationDeg = v; invalidate(); }
    public float getAlphaScale() { return alphaScale; }
    public void setAlphaScale(float v) { alphaScale = v; invalidate(); }
}
