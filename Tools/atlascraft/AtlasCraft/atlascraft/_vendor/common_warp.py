"""Import-safe coordinated semantic warp and exclusive interpolation.

Flow convention: [2,H,W] Y,X displacement. A-coordinate p samples B at
p+flow(p). All labels share this map. No region-specific transport is used.
Default regularization fixes X on the median column, both coordinates at
registered canal center, and both coordinates on the image boundary.
Native/registered anchors are returned unchanged at t=0 and t=1.
"""
import numpy as np
from .inverse_bilinear_newton import inverse_partial as _inverse_partial_newton
from scipy.ndimage import gaussian_filter as gf,map_coordinates as mc,zoom,distance_transform_edt as edt

def sdf(m):return (edt(m)-edt(~m)).astype('f4')

def sampling(m,coords):return mc(m,coords,order=1,mode='nearest',prefilter=False)

def propose_flow(a,b,verbose=False,canal_label=3023):
 ids=sorted((set(map(int,np.unique(a)))&set(map(int,np.unique(b))))-{0});flow=None;history=[]
 for factor,iterations in [(4,70),(2,45),(1,30)]:
  aa=np.stack([gf((a==i).astype('f4'),max(.8,factor*.6))[::factor,::factor]*(.6 if i==65535 else 2 if i==canal_label else 1) for i in ids]);bb=np.stack([gf((b==i).astype('f4'),max(.8,factor*.6))[::factor,::factor]*(.6 if i==65535 else 2 if i==canal_label else 1) for i in ids]);h,w=aa.shape[1:];coords=np.mgrid[:h,:w].astype('f4')
  if flow is None:flow=np.zeros((2,h,w),'f4')
  else:flow=np.stack([zoom(f,(h/f.shape[0],w/f.shape[1]),order=1)*2 for f in flow])
  gy,gx=np.gradient(bb,axis=(1,2));last=None
  for it in range(iterations):
   phi=coords+flow;warped=np.stack([sampling(ch,phi)for ch in bb]);wy=np.stack([sampling(ch,phi)for ch in gy]);wx=np.stack([sampling(ch,phi)for ch in gx]);diff=aa-warped
   hyy=gf(np.sum(wy*wy,axis=0),1)+.002;hxx=gf(np.sum(wx*wx,axis=0),1)+.002;hxy=gf(np.sum(wx*wy,axis=0),1);by=gf(np.sum(wy*diff,axis=0),1);bx=gf(np.sum(wx*diff,axis=0),1);det=hyy*hxx-hxy*hxy;dy=(hxx*by-hxy*bx)/det;dx=(hyy*bx-hxy*by)/det;length=np.hypot(dy,dx);scale=np.maximum(1,length/.6);update=np.stack([gf(dy/scale,1.3),gf(dx/scale,1.3)]).astype('f4')
   # Compose the same smooth incremental coordinate map for every identity.
   flow=update+np.stack([sampling(f,coords+update)for f in flow])
   if it%10==0:history.append({'scale':factor,'iteration':it,'oneHotMSE':float(np.mean(diff*diff))})
  
  if verbose: print('registered factor',factor,'loss',history[-1]['oneHotMSE'],flush=True)
 # Exact resampling to original shape if ceil-decimation dimensions differed.
 if flow.shape[1:]!=a.shape:flow=np.stack([zoom(f,(a.shape[0]/f.shape[0],a.shape[1]/f.shape[1]),order=1)for f in flow])
 dy_y,dy_x=np.gradient(flow[0]);dx_y,dx_x=np.gradient(flow[1]);jac=(1+dy_y)*(1+dx_x)-dy_x*dx_y
 return flow,{'history':history,'jacobianMin':float(jac.min()),'foldPixels':int(np.count_nonzero(jac<=0)),'displacementMaxPixels':float(np.hypot(*flow).max())}

register=propose_flow

def partial_jacobian_min(flow):
    """Exact minimum det(I+t*Dflow) for all bilinear-cell corners and all t."""
    flow=np.asarray(flow,dtype=float);grid=np.mgrid[:flow.shape[1],:flow.shape[2]].astype(float);p=grid+flow
    dy=[p[:,1:,:-1]-p[:,:-1,:-1],p[:,1:,1:]-p[:,:-1,1:]]
    dx=[p[:,:-1,1:]-p[:,:-1,:-1],p[:,1:,1:]-p[:,1:,:-1]]
    minimum=1.0
    for y in dy:
        for x in dx:
            trace=y[0]+x[1]-2;quad=(y[0]-1)*(x[1]-1)-y[1]*x[0]
            determinant=1+trace+quad
            t=np.clip(-trace/(2*np.where(quad>0,quad,np.inf)),0,1)
            stationary=np.where(quad>0,1+t*trace+t*t*quad,np.inf)
            minimum=min(minimum,float(np.minimum(np.minimum(1,determinant),stationary).min()))
    return minimum

def regularize_flow(raw_flow,sigma=12,min_jacobian=.2,midline_x=None,cc_center_yx=None):
    """Smooth and strength-backtrack a shared map; exact all-time Jacobian check."""
    flow=np.stack([gf(f,float(sigma))for f in raw_flow]).astype('f4');h,w=flow.shape[1:]
    cy,cx=cc_center_yx if cc_center_yx is not None else (h//2,w//2)
    mid=w//2 if midline_x is None else midline_x;y,x=np.mgrid[:h,:w]
    # Broad, subtractive landmark correction avoids a sharp annular gradient.
    flow[1]-=flow[1,:,mid,None]*np.exp(-.5*((x-mid)/30)**2)
    center_displacement=flow[:,cy,cx].copy()
    flow-=center_displacement[:,None,None]*np.exp(-.5*((x-cx)**2+(y-cy)**2)/30**2)
    # Smooth identity boundary taper has zero slope at either end.
    taper=np.clip(np.minimum.reduce([x,w-1-x,y,h-1-y])/40,0,1)
    flow*=taper*taper*(3-2*taper)
    strength=1.0
    while partial_jacobian_min(flow*strength)<min_jacobian:
        strength*=.85
        if strength<1e-6:raise RuntimeError('Unable to regularize common warp.')
    flow*=strength
    return flow,{'sigmaPixels':float(sigma),'strength':strength,'minimumAllPartialCornerJacobian':partial_jacobian_min(flow),'midlineXFixed':int(mid),'canalCenterYXFixed':[int(cy),int(cx)],'imageBoundaryIdentity':True,'landmarkPinSigmaPixels':30,'identityBoundaryTaperPixels':40,'coordinateConvention':'p in A -> p+flow(p) in B; displacement order Y,X'}

def inverse_partial(flow,w,iterations=120,tolerance=1e-4):
    """Exact bilinear Jacobian with bounded, residual-decreasing Newton updates."""
    return _inverse_partial_newton(flow,w,iterations=iterations,tolerance=tolerance)

def prepare_pair(a,b,flow):
    assert a.shape==b.shape==flow.shape[1:]
    ids=sorted((set(map(int,np.unique(a)))|set(map(int,np.unique(b))))-{0})
    distances=[]
    for rid in ids:
        ma=a==rid;mb=b==rid;distances.append((sdf(ma)if ma.any()else None,sdf(mb)if mb.any()else None))
    return {'a':a,'b':b,'flow':flow,'ids':ids,'distances':distances,'tissue0':sdf(a!=0),'tissue1':sdf(b!=0)}

def interpolate_prepared(pair,t,negative_to_unknown=False,return_scores=False):
    """Shared geometric warp + one winner/voxel. Negative scores may still win.

    Unresolved65535 is a normal source-supported competitor. Setting
    negative_to_unknown=True reproduces the explicitly conservative trial.
    """
    a,b,flow=pair['a'],pair['b'],pair['flow'];w=t*t*(3-2*t)
    if t<=0:return a.copy(),{'anchorExact':True,'fraction':0.0}
    if t>=1:return b.copy(),{'anchorExact':True,'fraction':1.0}
    ca,residual=inverse_partial(flow,w);cb=ca+np.stack([sampling(f,ca)for f in flow])
    inside=((1-w)*sampling(pair['tissue0'],ca)+w*sampling(pair['tissue1'],cb))>0
    best=np.full(a.shape,-np.inf,'f4');result=np.zeros(a.shape,np.uint16);scores=[];supports=[]
    for rid,(d0,d1) in zip(pair['ids'],pair['distances']):
        if d0 is None:q=w*sampling(d1,cb)-(1-w)*(d1.max()+1);radius=d1.max()
        elif d1 is None:q=(1-w)*sampling(d0,ca)-w*(d0.max()+1);radius=d0.max()
        else:q=(1-w)*sampling(d0,ca)+w*sampling(d1,cb);radius=(1-w)*d0.max()+w*d1.max()
        support=(q>0)&inside;q=q/max(radius,1);hit=q>best;result[hit]=rid;best[hit]=q[hit]
        if return_scores:scores.append(q);supports.append(support)
    nonpositive=inside&(best<=0)
    if negative_to_unknown:result[nonpositive]=65535
    result[~inside]=0
    stats={'fraction':float(t),'smoothstepWeight':float(w),'anchorExact':False,'inverseResidualPixels':residual,'nonpositiveWinnerPixels':int(nonpositive.sum()),'unresolvedPixels':int((result==65535).sum()),'tissuePixels':int(inside.sum()),'onlyAnchorUnionIDs':bool(set(map(int,np.unique(result)))<=set(pair['ids'])|{0})}
    if return_scores:stats.update(scores=np.stack(scores),ids=np.array(pair['ids'],np.uint16),inside=inside,positiveSupports=np.stack(supports),coordinatesA=ca,coordinatesB=cb)
    return result,stats

def interpolate(a,b,flow,t,negative_to_unknown=False,return_scores=False):
    return interpolate_prepared(prepare_pair(a,b,flow),t,negative_to_unknown,return_scores)
