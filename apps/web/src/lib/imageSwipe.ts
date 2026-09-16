import type { DOMAttributes, PointerEvent } from "react";

const DRAG_SLOP = 10;
const SWIPE_DISTANCE = 40;

interface Gesture {
  id: number;
  x: number;
  y: number;
  axis?: "horizontal" | "vertical";
  element: HTMLElement;
}

/** Single-pointer image navigation; leave vertical scrolling and pinch zoom to the browser. */
export function createImageSwipeHandlers(onSwipe: (step: -1 | 1) => void): DOMAttributes<HTMLElement> {
  let gesture: Gesture | undefined;
  let suppressClick = false;

  const release = () => {
    const previous = gesture;
    gesture = undefined;
    if (previous?.element.hasPointerCapture(previous.id)) {
      previous.element.releasePointerCapture(previous.id);
    }
  };

  const track = (event: PointerEvent<HTMLElement>) => {
    if (!gesture || event.pointerId !== gesture.id) return;
    const dx = event.clientX - gesture.x;
    const dy = event.clientY - gesture.y;
    if (Math.max(Math.abs(dx), Math.abs(dy)) >= DRAG_SLOP) {
      suppressClick = true;
      gesture.axis ??= Math.abs(dx) > Math.abs(dy) ? "horizontal" : "vertical";
    }
    return { dx, dy, axis: gesture.axis };
  };

  const cancel = (event: PointerEvent<HTMLElement>) => {
    if (gesture?.id !== event.pointerId) return;
    suppressClick = true;
    release();
  };

  return {
    onPointerDown(event) {
      if (!event.isPrimary) {
        // A second finger belongs to pinch zoom, never to image navigation.
        suppressClick = true;
        release();
        return;
      }
      if (event.button !== 0) return;
      suppressClick = false;
      release();
      const control = (event.target as Element).closest("button, a, input, textarea, select, [role='button']");
      // Nested controls keep their own normal clicks.
      if (control && control !== event.currentTarget) return;
      gesture = { id: event.pointerId, x: event.clientX, y: event.clientY, element: event.currentTarget };
      event.currentTarget.setPointerCapture(event.pointerId);
    },
    onPointerMove(event) {
      const movement = track(event);
      if (movement?.axis === "horizontal" && event.cancelable) event.preventDefault();
    },
    onPointerUp(event) {
      const movement = track(event);
      if (gesture?.id === event.pointerId) release();
      if (movement?.axis === "horizontal"
        && Math.abs(movement.dx) >= SWIPE_DISTANCE
        && Math.abs(movement.dx) > Math.abs(movement.dy) * 1.25) {
        onSwipe(movement.dx < 0 ? 1 : -1);
      }
    },
    onPointerCancel: cancel,
    onLostPointerCapture: cancel,
    onClickCapture(event) {
      // A drag must not turn into Dialog.Trigger's click-to-enlarge. A fresh
      // pointerdown clears this guard; detail=0 preserves keyboard activation.
      if (suppressClick && event.detail !== 0) {
        event.preventDefault();
        event.stopPropagation();
      }
      suppressClick = false;
    },
    onDragStart(event) {
      event.preventDefault();
    },
  };

}
